#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Qui répond sur un port : l'échelle de reconnaissance, et son transport.

Un port dit OÙ frapper, jamais QUI répond : 8080 héberge llama.cpp, LocalAI et
Open WebUI, 5000 héberge text-generation-webui et TabbyAPI, et `/v1/models`
est servi par onze serveurs sur douze. L'identité se lit donc dans le CORPS
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
)

# Le plafond de lecture par réponse. Une page d'administration de routeur ou
# un catalogue de plusieurs milliers de modèles répond volontiers à ces
# chemins ; la reconnaissance se joue dans les premiers octets.
BODY_CAP = 8192

# GPT4All n'expose aucun point de terminaison qui lui soit propre : son étage
# ne s'atteint que par élimination, et seulement sur ce port.
GPT4ALL_PORT = 4891

# OpenAI distant se tranche par le nom d'hôte. Un scan ne le touche jamais :
# il coûte un jeton et n'est pas sur le réseau qu'on balaie.
OPENAI_HOST = "api.openai.com"

OLLAMA_ROOT = b"Ollama is running"
JAN_TITLE = "Jan API Server Endpoints"

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
    """

    software: str = ""
    version: str = ""
    models: tuple[str, ...] = ()
    unknown: frozenset[str] = frozenset()


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


# Étage 11 — llama.cpp derrière un mandataire inverse, qui ne publie souvent
# que `/v1`. Le champ `owned_by` survit au masquage de `/props`.
def _llamacpp_proxy(bodies, port, host):
    for entry in _entries(_json(bodies, "/v1/models")):
        if entry.get("owned_by") == "llamacpp":
            return ""
    return None


# Étage 12 — GPT4All, par élimination : rien au-dessus n'a reconnu, le port
# est le sien, et une liste OpenAI est bien là. Le port seul ne suffit pas —
# une page d'administration écoute aussi sur des ports d'application.
def _gpt4all(bodies, port, host):
    if port != GPT4ALL_PORT:
        return None
    data = _json(bodies, "/v1/models")
    if isinstance(data, dict) and isinstance(data.get("data"), list):
        return ""
    return None


# Étage 13 — OpenAI distant, tranché par le nom d'hôte. Aucun balayage ne
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
    Probe("llamacpp", ("/v1/models",), _llamacpp_proxy),
    Probe("gpt4all", ("/v1/models",), _gpt4all),
    Probe("openai", (), _openai),
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
    """
    names: list[str] = []
    for path in ("/v1/models", "/api/v0/models", "/api/v1/models"):
        for entry in _entries(_json(bodies, path)):
            name = _text(entry, "id")
            if name and name not in names:
                names.append(name)
    tags = _json(bodies, "/api/tags")
    if isinstance(tags, dict) and isinstance(tags.get("models"), list):
        for entry in tags["models"]:
            name = _text(entry, "name")
            if name and name not in names:
                names.append(name)
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
        return Fingerprint(probe.software, version, models, frozenset(unknown))
    unknown = {"software", "version"}
    if not models:
        unknown.add("models")
    return Fingerprint("", "", models, frozenset(unknown))


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
) -> dict[str, tuple[int, bytes]]:
    """Frappe le plan et rend les corps arrivés. Le transport, et rien d'autre.

    `http_get(url, timeout)` rend (statut, octets) et se remplace en test ;
    la réalisation par défaut passe par la bibliothèque standard pour pouvoir
    plafonner la lecture. `budget` est le TOTAL de la collecte : le délai de
    chaque requête est ce qu'il en reste, donc un écouteur bloqué coûte le
    budget une fois et non une fois par chemin.

    Ne lève pas pour un port mort, une page HTML, un 401, un 503 ou un corps
    coupé : ce sont des résultats, et l'appelant les lit par `identify`. Un
    chemin absent du dictionnaire n'a rien rendu.
    """
    if http_get is None:
        http_get = functools.partial(_http_get, max_bytes=max_bytes)
    bodies: dict[str, tuple[int, bytes]] = {}
    deadline = time.monotonic() + budget
    for _method, path in probe_plan():
        left = deadline - time.monotonic()
        if left <= 0:
            break
        try:
            status, body = http_get(f"http://{host}:{port}{path}", left)
        except DEAD:
            break
        except Exception:
            # Un délai dépassé, une réponse illisible, une coupure : le
            # chemin reste absent et les suivants gardent leur chance.
            continue
        # Le plafond est celui du collecteur, pas celui du transport : un
        # `http_get` injecté qui l'ignorerait ne remplit pas la mémoire.
        bodies[path] = (status, bytes(body[:max_bytes]))
    return bodies
