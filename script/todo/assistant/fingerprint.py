#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Qui répond sur un port : l'échelle de reconnaissance, et son transport.

Un port dit OÙ frapper, jamais QUI répond : 8080 héberge llama.cpp, LocalAI et
Open WebUI, 5000 héberge text-generation-webui et TabbyAPI, et `/v1/models`
est servi par douze serveurs sur treize. L'identité se lit donc dans le CORPS
d'une réponse, dans un ordre fixe, et le premier accord arrête l'échelle.

Cet ordre porte tout le raisonnement, et son premier étage en est la raison :
LocalAI réémet l'API native d'Ollama EN ENTIER — `/api/tags`, `/api/show`,
`/api/ps`, `/api/version` — et rend jusqu'à la chaîne « Ollama is running »
sur « / ». Les points de terminaison propres à Ollama n'identifient donc pas
Ollama. LocalAI s'écarte le PREMIER, par `GET /readyz`, qu'Ollama ne possède
pas et où il rend 404 ; l'étage Ollama n'est atteignable que parce que cet
écart a déjà eu lieu.

Le module tient deux moitiés qui ne se mélangent pas. `identify` est PUR : il
ne reçoit que des octets déjà lus, donc l'ordre de l'échelle se vérifie sans
ouvrir une socket. `collect` ne fait que le transport, donc le plafond de
lecture et les délais se vérifient contre un serveur qui se conduit mal.

La découverte n'émet que des GET, sans corps et sans en-tête `Authorization` :
un balayage ne doit pouvoir ni charger un modèle, ni dépenser un jeton. Le
`POST /api/show` d'Ollama appartient à l'interrogation des capacités, lancée
après que l'utilisateur a choisi un serveur.

Trois réponses que le transport rend comme des RÉSULTATS et non des échecs :
un 503 « starting » ou « Loading model » est vivant et identifié, un 401 est
un accord de reconnaissance et jamais une invitation à saisir une clé, et un
corps tronqué vaut ce qui en est arrivé.
"""

from __future__ import annotations

import functools
import http.client
import json
import re
import socket
import time
import urllib.parse
from dataclasses import dataclass
from typing import Callable

# Les ports à frapper, dans cet ordre. Le port ne nomme rien : il ne fait
# qu'ouvrir la question que l'échelle tranche.
PORTS: tuple[int, ...] = (
    11434,
    1234,
    5001,
    1337,
    4891,
    8080,
    5000,
    8000,
    3000,
    8081,
    5002,
    52415,
)

# Le plafond de lecture d'une réponse d'EMPREINTE. Une page d'administration
# de routeur répond volontiers à ces chemins, et la reconnaissance se joue
# dans les premiers octets : lire plus loin ne nomme personne de mieux.
BODY_CAP = 8192

# Le plafond d'un CATALOGUE, plus haut parce qu'un catalogue est la seule
# réponse dont la taille suit ce que le serveur OFFRE, et non ce qu'il EST.
# Une centaine de modèles dépasse le plafond d'empreinte, et le JSON s'arrête
# alors en plein milieu d'une entrée : il ne s'analyse plus, aucun modèle
# n'est lu, et un étage qui lit le catalogue ne reconnaît plus rien — le
# serveur se conclut MUET à l'instant où il énumérait son offre.
#
# Le plafond demeure malgré tout, et il est DIMENSIONNÉ, non pas généreux :
# un serveur qui offre cent vingt modèles en décrit environ cinquante-cinq
# kilooctets, donc ce plafond-ci laisse près de cinq fois la plus grande
# offre observée. Le monter encore ne rend aucun serveur de plus lisible, et
# coûte des deux côtés : le corps vient d'un tiers, et les noms qu'on en tire
# sont RETENUS par le balayage pour chaque hôte reconnu. Ce qui dépasse
# retombe sur le cas coupé, sans planter.
CATALOG_CAP = 256 << 10

# Les chemins dont le corps est un catalogue. Exactement ceux que `_models`
# analyse : partout ailleurs, la taille de la réponse ne dépend pas de ce que
# le serveur offre, et le plafond d'empreinte suffit.
CATALOG_PATHS = (
    "/v1/models",
    "/api/v0/models",
    "/api/v1/models",
    "/api/tags",
)

# GPT4All n'expose aucun point de terminaison qui lui soit propre : son étage
# ne s'atteint que par élimination, et seulement sur ce port.
GPT4ALL_PORT = 4891

# OpenAI distant se tranche par le nom d'hôte. Un scan ne le touche jamais :
# il coûte un jeton et n'est pas sur le réseau qu'on balaie.
OPENAI_HOST = "api.openai.com"

OLLAMA_ROOT = b"Ollama is running"
JAN_TITLE = "Jan API Server Endpoints"

# Le chemin qui dit ce qu'exo tient CHARGÉ. Son état complet le porte aussi,
# noyé dans plusieurs centaines de kilooctets de topologie, de disques et de
# téléchargements ; l'accesseur par sous-chemin rend les mêmes instances en
# un peu plus d'un kilooctet, donc il est sondable là où l'état entier ne
# l'est pas.
EXO_INSTANCES = "/state/instances"

# Un numéro de version plausible. L'étage Ollama s'en sert pour confirmer que
# `/api/version` répond bien ce qu'Ollama y répond, et non le JSON d'autre
# chose monté au même endroit.
SEMVER = re.compile(r"^\d+\.\d+")

# Ce qui prouve que rien n'écoute : les chemins suivants seraient refusés de
# la même façon, donc la collecte s'arrête au lieu de recommencer quinze fois
# par hôte mort.
DEAD = (ConnectionRefusedError, socket.gaierror)


@dataclass(frozen=True)
class Fingerprint:
    """Ce qu'une réponse a prouvé, et ce qu'elle n'a pas dit.

    `software` est la chaîne vide quand aucun étage n'a reconnu quoi que ce
    soit : un point de terminaison génériquement compatible OpenAI en est un
    cas normal, pas une panne. `unknown` nomme les champs que les corps ne
    portaient pas, parmi « software », « version » et « models » — de quoi
    afficher « ? » sur ceux-là plutôt que de deviner.

    `models` est ce que le serveur ANNONCE, `served` ce qu'il SERT à
    l'instant. Les deux se confondent chez la plupart : leur catalogue ne
    nomme que ce qui est chargé. Un moteur qui répartit des modèles sur
    plusieurs machines annonce en revanche tout ce qu'il SAIT faire tourner
    — des centaines d'entrées — et n'en tient qu'une poignée en mémoire ;
    demander une autre rend un refus, pas une réponse lente.

    `served` VIDE signifie « le serveur ne le dit pas », jamais « rien n'est
    servable » : l'immense majorité n'expose aucun point de terminaison qui
    réponde à la question, et traiter leur silence comme un refus rendrait
    tout serveur inutilisable.
    """

    software: str = ""
    version: str = ""
    models: tuple[str, ...] = ()
    unknown: frozenset[str] = frozenset()
    served: tuple[str, ...] = ()


@dataclass(frozen=True)
class Probe:
    """Un étage : le logiciel qu'il nomme, ce qu'il lit, ce qui l'accorde.

    `decide(bodies, port, host)` rend la version lue, la chaîne vide quand le
    corps ne la porte pas, et `None` quand l'étage ne reconnaît rien.
    Distinguer « accord sans version » de « pas d'accord » est ce qui permet
    de nommer un serveur dont le numéro reste inconnu.
    """

    software: str
    paths: tuple[str, ...]
    decide: Callable[[dict[str, tuple[int, bytes]], int, str], str | None]


def _answer(
    bodies: dict[str, tuple[int, bytes]], path: str
) -> tuple[int, bytes] | None:
    """Le couple (statut, octets) d'un chemin, ou `None`.

    Un chemin absent de la table n'a pas été sondé ou n'a rien rendu : les
    deux se lisent pareil, et aucun étage ne doit distinguer les deux.
    """
    answer = bodies.get(path)
    if not isinstance(answer, tuple) or len(answer) != 2:
        return None
    return answer


def _json(
    bodies: dict[str, tuple[int, bytes]],
    path: str,
    *,
    statuses: tuple[int, ...] = (200,),
) -> object:
    """Le corps d'un chemin analysé en JSON, ou `None`.

    Rend `None` sur un statut non voulu, sur du HTML, sur un corps vide et
    sur un corps coupé en plein milieu : chaque analyse est enveloppée parce
    qu'un portail captif répond 200 en HTML à n'importe quel chemin.
    """
    answer = _answer(bodies, path)
    if answer is None or answer[0] not in statuses:
        return None
    try:
        return json.loads(answer[1])
    except Exception:
        return None


def _entries(data: object) -> list[dict]:
    """Les entrées d'une liste OpenAI `{"data": [...]}`, sinon une liste vide.

    Ne garde que les éléments qui sont des mappings : une liste d'identifiants
    nus ne porte aucun champ à lire.
    """
    if not isinstance(data, dict):
        return []
    entries = data.get("data")
    if not isinstance(entries, list):
        return []
    return [entry for entry in entries if isinstance(entry, dict)]


def _text(data: object, key: str) -> str:
    """La valeur textuelle d'une clé d'un mapping, sinon la chaîne vide."""
    if isinstance(data, dict):
        value = data.get(key)
        if isinstance(value, str):
            return value
    return ""


# Étage 1 — LocalAI. `/readyz` est le seul point que LocalAI possède et
# qu'Ollama ignore : Ollama y rend 404. La version ne se lit PAS ici, et pas
# ailleurs non plus : LocalAI annonce un littéral figé sur `/api/version`,
# indépendant de sa propre version, et ce numéro-là existe aussi comme
# version réelle d'Ollama — il ne sépare donc rien à lui seul.
def _localai(bodies, port, host):
    answer = _answer(bodies, "/readyz")
    if answer is None:
        return None
    status, body = answer
    if status == 200 and not body.strip():
        return ""
    if status == 503 and _text(
        _json(bodies, "/readyz", statuses=(503,)), "status"
    ):
        # Le préchargement d'un modèle : le serveur est identifié et vivant,
        # il n'est pas encore prêt à répondre.
        return ""
    return None


# Étage 2 — KoboldCpp se nomme lui-même dans le champ `result`.
def _koboldcpp(bodies, port, host):
    data = _json(bodies, "/api/extra/version")
    if _text(data, "result") == "KoboldCpp":
        return _text(data, "version")
    return None


# Étage 3 — Jan se nomme dans le titre de son schéma OpenAPI.
def _jan(bodies, port, host):
    data = _json(bodies, "/openapi.json")
    if not isinstance(data, dict):
        return None
    info = data.get("info")
    if _text(info, "title") == JAN_TITLE:
        return _text(info, "version")
    return None


# Étage 4 — Open WebUI est la seule interface à publier `deployment_id`.
def _open_webui(bodies, port, host):
    data = _json(bodies, "/api/config")
    if isinstance(data, dict) and "deployment_id" in data:
        return _text(data, "version")
    return None


# Étage 5 — llama.cpp. Les deux clés sont exigées ENSEMBLE : `build_info` seul
# se retrouve sur des empaquetages qui recopient le champ, et
# `chat_template_caps` est ce que le serveur amont sert vraiment sur `/props`.
def _llamacpp(bodies, port, host):
    data = _json(bodies, "/props")
    if not isinstance(data, dict):
        return None
    if "build_info" in data and "chat_template_caps" in data:
        return _text(data, "build_info")
    return None


# Étage 6 — vLLM. Le chemin est `/version`, PAS `/api/version` : ce dernier
# appartient à Ollama et à LocalAI, et les confondre nomme vLLM sur toutes
# les machines Ollama.
def _vllm(bodies, port, host):
    data = _json(bodies, "/version")
    if isinstance(data, dict) and "version" in data:
        return _text(data, "version")
    return None


# Étage 7 — LM Studio. Son catalogue porte des champs que la forme OpenAI
# n'a pas ; l'ancien chemin `/api/v0/models` et le nouveau se lisent pareil.
def _lmstudio(bodies, port, host):
    for path in ("/api/v0/models", "/api/v1/models"):
        for entry in _entries(_json(bodies, path)):
            if "compatibility_type" in entry or "max_context_length" in entry:
                return ""
    return None


# Étage 8 — Ollama, atteignable seulement parce que l'étage 1 a écarté
# LocalAI. Le catalogue et la racine sont exigés ENSEMBLE, et `/api/version`
# confirme sans jamais être exigé : une confirmation absente laisse l'accord
# debout, seul un champ `version` qui ne ressemble pas à un numéro le retire —
# c'est alors que du JSON étranger est monté sous ce chemin.
def _ollama(bodies, port, host):
    tags = _json(bodies, "/api/tags")
    if not isinstance(tags, dict) or not isinstance(tags.get("models"), list):
        return None
    root = _answer(bodies, "/")
    if root is None or root[0] != 200 or OLLAMA_ROOT not in root[1]:
        return None
    data = _json(bodies, "/api/version")
    if not isinstance(data, dict) or "version" not in data:
        return ""
    version = _text(data, "version")
    return version if SEMVER.match(version) else None


# Étage 9 — text-generation-webui, par un chemin interne qu'il est seul à
# monter sous `/v1`.
def _textgen_webui(bodies, port, host):
    data = _json(bodies, "/v1/internal/model/info")
    if isinstance(data, dict) and data:
        return ""
    return None


# Étage 10 — TabbyAPI. `/v1/model` au singulier n'existe que chez lui, et il
# exige une clé par défaut : un 401 est donc un ACCORD de reconnaissance. Le
# 200 couvre la configuration qui a désactivé l'authentification.
def _tabbyapi(bodies, port, host):
    for path in ("/v1/model", "/v1/template/list"):
        answer = _answer(bodies, path)
        if answer is not None and answer[0] == 401:
            return ""
    if isinstance(_json(bodies, "/v1/model"), dict):
        return ""
    return None


# Étage 11 — exo, moteur d'inférence RÉPARTI sur plusieurs machines. Deux
# lectures le nomment, et aucune n'est de trop.
#
# `/node_id` rend l'identifiant du pair dans la grappe — une chaîne JSON nue,
# là où tout le reste de l'échelle rend des objets — et c'est la seule
# lecture qui survive à un catalogue trop gros pour être analysé, puisqu'elle
# tient en quelques dizaines d'octets.
#
# `owned_by` dans le catalogue prend le relais quand un mandataire inverse ne
# publie que `/v1`, exactement comme il le fait pour l'étage suivant.
#
# Aucune version n'est rendue : exo n'annonce la sienne nulle part, et le
# numéro que porte son schéma OpenAPI est le défaut du cadre web qui le sert,
# pas le sien.
def _exo(bodies, port, host):
    if isinstance(_json(bodies, "/node_id"), str):
        return ""
    for entry in _entries(_json(bodies, "/v1/models")):
        if entry.get("owned_by") == "exo":
            return ""
    return None


# Étage 12 — llama.cpp derrière un mandataire inverse, qui ne publie souvent
# que `/v1`. Le champ `owned_by` survit au masquage de `/props`.
def _llamacpp_proxy(bodies, port, host):
    for entry in _entries(_json(bodies, "/v1/models")):
        if entry.get("owned_by") == "llamacpp":
            return ""
    return None


# Étage 13 — GPT4All, par élimination : rien au-dessus n'a reconnu, le port
# est le sien, et une liste OpenAI est bien là. Le port seul ne suffit pas —
# une page d'administration écoute aussi sur des ports d'application.
def _gpt4all(bodies, port, host):
    if port != GPT4ALL_PORT:
        return None
    data = _json(bodies, "/v1/models")
    if isinstance(data, dict) and isinstance(data.get("data"), list):
        return ""
    return None


# Étage 14 — OpenAI distant, tranché par le nom d'hôte. Aucun balayage ne
# l'atteint : c'est la configuration qui le nomme.
def _openai(bodies, port, host):
    if host.strip().lower().rstrip(".") == OPENAI_HOST:
        return ""
    return None


# L'échelle, dans l'ordre où elle est lue, arrêt au premier accord. LocalAI
# EN PREMIER : déplacer cet étage plus bas nomme « ollama » toutes les
# machines LocalAI, puisque LocalAI sert l'API native d'Ollama en entier.
LADDER: tuple[Probe, ...] = (
    Probe("localai", ("/readyz",), _localai),
    Probe("koboldcpp", ("/api/extra/version",), _koboldcpp),
    Probe("jan", ("/openapi.json",), _jan),
    Probe("open_webui", ("/api/config",), _open_webui),
    Probe("llamacpp", ("/props",), _llamacpp),
    Probe("vllm", ("/version",), _vllm),
    Probe("lmstudio", ("/api/v0/models", "/api/v1/models"), _lmstudio),
    Probe("ollama", ("/api/tags", "/", "/api/version"), _ollama),
    Probe("textgen_webui", ("/v1/internal/model/info",), _textgen_webui),
    Probe("tabbyapi", ("/v1/model", "/v1/template/list"), _tabbyapi),
    Probe("exo", ("/node_id", "/v1/models", EXO_INSTANCES), _exo),
    Probe("llamacpp", ("/v1/models",), _llamacpp_proxy),
    Probe("gpt4all", ("/v1/models",), _gpt4all),
    Probe("openai", (), _openai),
)


def _exo_served(bodies) -> tuple[str, ...]:
    """Les modèles qu'exo tient CHARGÉS, lus dans ses instances.

    Son catalogue nomme tout ce qu'il sait faire tourner ; une instance est
    ce qui occupe vraiment de la mémoire, et une seule tourne d'ordinaire.
    Chaque instance porte son genre, puis une assignation de tessons dont le
    `modelId` nomme le modèle servi.

    Rend les modèles dans l'ordre de lecture, sans doublon : deux instances
    du même modèle sont un cas normal d'un moteur réparti.
    """
    instances = _json(bodies, EXO_INSTANCES)
    if not isinstance(instances, dict):
        return ()
    found: list[str] = []
    for instance in instances.values():
        if not isinstance(instance, dict):
            continue
        for kind in instance.values():
            if not isinstance(kind, dict):
                continue
            name = _text(kind.get("shardAssignments"), "modelId")
            if name and name not in found:
                found.append(name)
    return tuple(found)


# Ce qu'il faut demander à un logiciel pour savoir ce qu'il SERT, et qui le
# lit. Un logiciel absent de la table ne distingue pas les deux : son
# catalogue ne nomme que des modèles chargés, et l'interroger de plus
# coûterait une requête pour apprendre ce qu'on sait déjà.
SERVED_PATHS: dict[str, tuple[str, ...]] = {"exo": (EXO_INSTANCES,)}
SERVED_READERS = {"exo": _exo_served}


def served_models(software: str, bodies) -> tuple[str, ...]:
    """Ce que `software` SERT, lu dans les corps déjà collectés. PURE.

    Rend un tuple VIDE quand le logiciel ne répond pas à la question, ce qui
    est le cas de presque tous : c'est « il ne le dit pas », et jamais « rien
    n'est servable ».
    """
    lecteur = SERVED_READERS.get(software)
    return lecteur(bodies) if lecteur else ()


def collect_served(
    software: str,
    host: str,
    port: int,
    *,
    http_get: Callable[[str, float], tuple[int, bytes]] | None = None,
    budget: float = 1.0,
) -> tuple[str, ...]:
    """Ce que `software` sert MAINTENANT, en frappant le strict nécessaire.

    Le pendant transporté de `served_models`, pour la question qui se repose
    alors qu'une empreinte est déjà connue : ce qu'un moteur tient chargé
    change pendant qu'on s'en sert, donc une lecture faite à la découverte ne
    répond plus à l'ouverture d'une conversation.

    Ne frappe QUE les chemins du logiciel nommé — un seul pour l'instant — au
    lieu du plan entier, parce que rouvrir une conversation ne doit pas
    coûter une reconnaissance complète.
    """
    paths = SERVED_PATHS.get(software)
    if not paths:
        return ()
    return served_models(
        software,
        collect(host, port, http_get=http_get, budget=budget, paths=paths),
    )


def probe_plan() -> list[tuple[str, str]]:
    """Les requêtes de la découverte, dans l'ordre de l'échelle, sans doublon.

    Rend des couples (méthode, chemin). La méthode est toujours GET, et elle
    figure dans le plan pour que l'exiger reste une contrainte lisible : un
    étage qui aurait besoin d'un autre verbe devrait aussi toucher le
    transport, qui ne sait faire que GET.
    """
    plan: list[tuple[str, str]] = []
    seen: set[str] = set()
    for probe in LADDER:
        for path in probe.paths:
            if path not in seen:
                seen.add(path)
                plan.append(("GET", path))
    return plan


def _models(bodies: dict[str, tuple[int, bytes]]) -> tuple[str, ...]:
    """Les noms de modèles annoncés, dédoublonnés, dans l'ordre de lecture.

    Se lit même quand aucun étage n'a reconnu le serveur : une liste de
    modèles est utile devant un point de terminaison anonyme.

    Le dédoublonnage passe par un ENSEMBLE et non par la liste en cours : le
    « in » d'une liste est linéaire, donc la fonction entière était
    quadratique, et le plafond d'un catalogue borne désormais le nombre de
    noms bien plus haut que celui d'une réponse d'empreinte. Un catalogue
    d'un mégaoctet demandait quinze secondes de calcul, pendant lesquelles
    le menu paraît figé — et ce temps-là est hors du budget de `collect`,
    qui ne borne que le transport.
    """
    names: list[str] = []
    seen: set[str] = set()

    def garder(name: str) -> None:
        if name and name not in seen:
            seen.add(name)
            names.append(name)

    for path in ("/v1/models", "/api/v0/models", "/api/v1/models"):
        for entry in _entries(_json(bodies, path)):
            garder(_text(entry, "id"))
    tags = _json(bodies, "/api/tags")
    if isinstance(tags, dict) and isinstance(tags.get("models"), list):
        for entry in tags["models"]:
            garder(_text(entry, "name"))
    return tuple(names)


def identify(
    bodies: dict[str, tuple[int, bytes]], *, port: int = 0, host: str = ""
) -> Fingerprint:
    """Qui répond, lu dans les corps déjà collectés. Fonction PURE.

    `bodies` associe un chemin à (statut, octets bruts) ; un chemin absent
    n'a pas été sondé ou n'a rien rendu. `port` ne sert qu'à l'étage
    d'élimination et `host` qu'à l'étage nommé par configuration : aucun des
    deux ne peut nommer un logiciel que le corps n'a pas prouvé.

    Ne lève jamais. Un corps vide, tronqué, HTML ou hostile rend une
    empreinte sans logiciel, ce qui est un résultat.
    """
    models = _models(bodies)
    for probe in LADDER:
        version = probe.decide(bodies, port, host)
        if version is None:
            continue
        unknown = set()
        if not version:
            unknown.add("version")
        if not models:
            unknown.add("models")
        return Fingerprint(
            probe.software,
            version,
            models,
            frozenset(unknown),
            served_models(probe.software, bodies),
        )
    unknown = {"software", "version"}
    if not models:
        unknown.add("models")
    return Fingerprint("", "", models, frozenset(unknown))


def _authority(host: str, port: int) -> str:
    """La partie « hôte:port » d'une URL, l'adresse IPv6 entre CROCHETS.

    Sans eux, les deux-points de l'adresse ne se distinguent pas de celui du
    port : l'analyse d'URL lève au lieu de rendre un hôte, et la cible passe
    pour illisible au lieu de simplement ne pas répondre. Un tunnel lié en
    IPv6 sur cette machine est le cas qui y mène sans qu'on ait rien tapé.
    """
    return f"[{host}]:{port}" if ":" in host else f"{host}:{port}"


def _http_get(
    url: str, timeout: float, *, max_bytes: int = BODY_CAP
) -> tuple[int, bytes]:
    """Un GET de la bibliothèque standard, dont le corps est PLAFONNÉ.

    Rend (statut, octets). Ne monte ni `Authorization`, ni corps, ni verbe
    autre que GET. Le plafond exige de lire la réponse par morceaux, ce que
    `requests` ne donne pas simplement : un serveur qui annonce huit
    mégaoctets ne doit pas en faire tenir huit en mémoire du menu.
    """
    parts = urllib.parse.urlsplit(url)
    conn = http.client.HTTPConnection(
        parts.hostname or "", parts.port or 80, timeout=timeout
    )
    try:
        conn.request("GET", parts.path or "/")
        response = conn.getresponse()
        return response.status, response.read(max_bytes)
    finally:
        conn.close()


def collect(
    host: str,
    port: int,
    *,
    http_get: Callable[[str, float], tuple[int, bytes]] | None = None,
    budget: float = 1.0,
    max_bytes: int = BODY_CAP,
    catalog_bytes: int = CATALOG_CAP,
    paths: tuple[str, ...] | None = None,
) -> dict[str, tuple[int, bytes]]:
    """Frappe le plan et rend les corps arrivés. Le transport, et rien d'autre.

    `http_get(url, timeout)` rend (statut, octets) et se remplace en test ;
    la réalisation par défaut passe par la bibliothèque standard pour pouvoir
    plafonner la lecture. `budget` est le TOTAL de la collecte : le délai de
    chaque requête est ce qu'il en reste, donc un écouteur bloqué coûte le
    budget une fois et non une fois par chemin.

    DEUX plafonds, choisis par le chemin. `max_bytes` borne une réponse
    d'empreinte, dont seuls les premiers octets servent ; `catalog_bytes`
    borne les chemins de `CATALOG_PATHS`, dont le corps grandit avec ce que
    le serveur offre et doit s'analyser ENTIER pour rendre un modèle. Un test
    qui veut voir une coupure partout abaisse les deux.

    `paths` restreint la frappe à ces chemins-là, dans cet ordre, au lieu du
    plan entier. Il sert la question posée à un serveur DÉJÀ reconnu — ce
    qu'il sert en ce moment — là où reconnaître une deuxième fois coûterait
    seize requêtes pour une réponse.

    Ne lève pas pour un port mort, une page HTML, un 401, un 503 ou un corps
    coupé : ce sont des résultats, et l'appelant les lit par `identify`. Un
    chemin absent du dictionnaire n'a rien rendu.
    """
    bodies: dict[str, tuple[int, bytes]] = {}
    deadline = time.monotonic() + budget
    voulus = (
        [("GET", path) for path in paths]
        if paths is not None
        else probe_plan()
    )
    for _method, path in voulus:
        left = deadline - time.monotonic()
        if left <= 0:
            break
        cap = catalog_bytes if path in CATALOG_PATHS else max_bytes
        # Le transport par défaut se plafonne par requête, parce que le
        # plafond dépend du chemin ; un transport injecté garde le contrat à
        # deux arguments, et c'est la coupe ci-dessous qui le borne.
        get = http_get or functools.partial(_http_get, max_bytes=cap)
        try:
            status, body = get(f"http://{_authority(host, port)}{path}", left)
        except DEAD:
            break
        except Exception:
            # Un délai dépassé, une réponse illisible, une coupure : le
            # chemin reste absent et les suivants gardent leur chance.
            continue
        # Le plafond est celui du collecteur, pas celui du transport : un
        # `http_get` injecté qui l'ignorerait ne remplit pas la mémoire.
        bodies[path] = (status, bytes(body[:cap]))
    return bodies
