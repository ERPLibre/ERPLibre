#!/usr/bin/env python3
# © 2025-2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Mandataire inverse de développement devant Odoo, sans nginx.

Visé : Odoo 18. Une seule adresse pour le navigateur : les pages vont au
port web d'Odoo (8069), le bus — /websocket — à son port dédié (8072). Odoo,
lancé avec proxy_mode, lit les en-têtes X-Forwarded-* posés ici.

Le mandataire ne lit que la TÊTE de chaque requête : il choisit le port,
réécrit les en-têtes, puis relaie les octets tels quels dans les deux sens.
Le corps n'est ni lu en entier ni décompressé, une réponse gzip ou en
morceaux passe à l'identique, et une connexion montée en WebSocket reste
ouverte tant qu'un des deux bouts parle.

Chaque connexion porte UNE requête : l'amont reçoit « Connection: close »,
ferme après sa réponse, et le navigateur rouvre pour la suivante. Relayer
plusieurs requêtes sur une connexion demanderait de suivre la longueur de
chaque corps ; pour un outil de poste, une connexion de plus est moins
chère que cette comptabilité. En production, nginx (script/nginx/) garde
la main.
"""

import argparse
import asyncio
import configparser
import ssl
import sys
import time
from dataclasses import dataclass

# Une tête au-delà est refusée (431) : aucun navigateur n'en envoie de si
# longue, et la lire en entier laisserait un client remplir la mémoire.
MAX_HEAD = 64 * 1024

DEFAULT_WEBSOCKET_PATHS = ("/websocket",)

# En-têtes propres à UN saut : jamais relayés tels quels. Upgrade et
# Connection sont reposés pour une montée en WebSocket.
HOP_BY_HOP = {
    "connection",
    "keep-alive",
    "proxy-connection",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailer",
    "upgrade",
}

# Posés par ce mandataire seul : la valeur d'un client est écartée, Odoo en
# proxy_mode prendrait sinon une adresse inventée pour celle du visiteur.
FORWARDED = {
    "x-forwarded-for",
    "x-forwarded-host",
    "x-forwarded-proto",
    "x-real-ip",
}

RELAY_CHUNK = 64 * 1024

# Délais de la mise en relation seulement, jamais du relais : une WebSocket
# ouverte reste muette des minutes entre deux notifications.
HEAD_TIMEOUT = 30.0
CONNECT_TIMEOUT = 10.0


@dataclass(frozen=True)
class ProxyConfig:
    """Réglages du mandataire.

    head_timeout borne l'attente de la tête d'une requête (408 au-delà),
    connect_timeout la connexion à Odoo (504). trust_forwarded prolonge les
    X-Forwarded-* reçus au lieu de les remplacer, pour un mandataire placé
    derrière un autre. log reçoit une ligne par requête ; None le rend muet.
    """

    odoo_host: str = "127.0.0.1"
    web_port: int = 8069
    websocket_port: int = 8072
    websocket_paths: tuple = DEFAULT_WEBSOCKET_PATHS
    forwarded_proto: str = "http"
    head_timeout: float = HEAD_TIMEOUT
    connect_timeout: float = CONNECT_TIMEOUT
    trust_forwarded: bool = False
    log: object = print


def read_odoo_config(path):
    """Les ports et réglages d'Odoo utiles au mandataire.

    Lit la section [options] d'un config.conf. Les anciens noms, xmlrpc_port
    et longpolling_port, servent de repli ; une option absente
    ou illisible — un fichier absent compris — garde le défaut d'Odoo.

    :return: {"web_port", "websocket_port", "proxy_mode", "workers"}
    """
    cfg = configparser.ConfigParser(interpolation=None)
    cfg.read(path)

    def entier(noms, defaut):
        for nom in noms:
            try:
                return cfg.getint("options", nom)
            except (configparser.Error, ValueError):
                continue
        return defaut

    try:
        proxy_mode = cfg.getboolean("options", "proxy_mode")
    except (configparser.Error, ValueError):
        proxy_mode = False
    return {
        "web_port": entier(("http_port", "xmlrpc_port"), 8069),
        "websocket_port": entier(("gevent_port", "longpolling_port"), 8072),
        "proxy_mode": proxy_mode,
        "workers": entier(("workers",), 0),
    }


def parse_head(head):
    """Découpe une tête de requête brute.

    :param head: octets jusqu'à la ligne vide « \\r\\n\\r\\n » comprise
    :return: (méthode, cible, version, [(nom, valeur), …]) dans l'ordre reçu
    :raises ValueError: ligne de requête ou en-tête illisible
    """
    lines = head.decode("latin-1").split("\r\n")
    parts = lines[0].split(" ")
    if len(parts) != 3 or not parts[2].startswith("HTTP/"):
        raise ValueError("ligne de requête illisible")
    method, target, version = parts
    headers = []
    for line in lines[1:]:
        if not line:
            continue
        name, sep, value = line.partition(":")
        if not sep or not name or name != name.strip():
            raise ValueError("en-tête illisible")
        headers.append((name, value.strip()))
    return method, target, version, headers


def is_websocket_path(target, config):
    """Vrai quand la cible vise le bus, comparée par segment entier.

    « /websocket » et « /websocket/… » vont au bus, « /websocketX » non.
    """
    path = target.split("?", 1)[0]
    return any(
        path == p or path.startswith(p.rstrip("/") + "/")
        for p in config.websocket_paths
    )


def is_upgrade(headers):
    """Vrai quand la requête demande une montée de protocole (WebSocket)."""
    connection = ",".join(
        v for n, v in headers if n.lower() == "connection"
    ).lower()
    has_upgrade = any(n.lower() == "upgrade" for n, _ in headers)
    return has_upgrade and "upgrade" in connection


def rewrite_head(method, target, version, headers, client_ip, config):
    """La tête envoyée à Odoo.

    Retire les en-têtes d'un saut et ceux du mandataire venus du client, pose
    X-Forwarded-For/-Host/-Proto et X-Real-IP, puis la conduite de connexion :
    « Upgrade » et « Connection: Upgrade » pour une montée en WebSocket,
    « Connection: close » sinon.

    :return: la tête en octets, ligne vide finale comprise
    """
    upgrade = is_upgrade(headers)

    def first(name):
        return next((v for n, v in headers if n.lower() == name), "")

    upgrade_value = first("upgrade")
    host = first("host")
    forwarded_for = client_ip
    real_ip = client_ip
    forwarded_host = host
    forwarded_proto = config.forwarded_proto
    if config.trust_forwarded:
        # Derrière un autre mandataire : sa chaîne est prolongée, et ce qu'il
        # dit de l'hôte et du protocole du visiteur l'emporte.
        chain = ", ".join(
            v for n, v in headers if n.lower() == "x-forwarded-for"
        )
        if chain:
            forwarded_for = f"{chain}, {client_ip}"
            real_ip = chain.split(",")[0].strip()
        real_ip = first("x-real-ip") or real_ip
        forwarded_host = first("x-forwarded-host") or host
        forwarded_proto = first("x-forwarded-proto") or forwarded_proto
    kept = [
        (n, v)
        for n, v in headers
        if n.lower() not in HOP_BY_HOP and n.lower() not in FORWARDED
    ]
    kept += [
        ("X-Forwarded-For", forwarded_for),
        ("X-Real-IP", real_ip),
        ("X-Forwarded-Host", forwarded_host),
        ("X-Forwarded-Proto", forwarded_proto),
    ]
    if upgrade:
        kept += [("Upgrade", upgrade_value), ("Connection", "Upgrade")]
    else:
        kept.append(("Connection", "close"))
    lines = [f"{method} {target} {version}"]
    lines += [f"{n}: {v}" for n, v in kept]
    return ("\r\n".join(lines) + "\r\n\r\n").encode("latin-1")


async def _reply_error(writer, status, reason, detail=""):
    body = f"{status} {reason}\n{detail}".encode()
    writer.write(
        f"HTTP/1.1 {status} {reason}\r\nContent-Type: text/plain\r\n"
        f"Content-Length: {len(body)}\r\nConnection: close\r\n\r\n".encode()
        + body
    )
    try:
        await writer.drain()
    except ConnectionError:
        pass


async def _pipe(reader, writer, half_close, on_first=None):
    """Copie reader vers writer jusqu'à la fin du flux.

    half_close : à la fin, fermer seulement l'écriture (write_eof) plutôt que
    rien — le client qui a fini d'envoyer attend encore la réponse.
    on_first reçoit le premier bloc lu, sans le retenir : le journal y lit
    le statut de la réponse.
    """
    try:
        while data := await reader.read(RELAY_CHUNK):
            if on_first is not None:
                on_first(data)
                on_first = None
            writer.write(data)
            await writer.drain()
        if half_close and writer.can_write_eof():
            writer.write_eof()
    except (ConnectionError, OSError):
        pass


def _status_of(chunk):
    """Le statut d'une réponse d'après son premier bloc, « ? » sinon."""
    parts = chunk.split(b" ", 2)
    if len(parts) >= 2 and parts[0].startswith(b"HTTP/"):
        return parts[1].decode("latin-1")
    return "?"


def unreachable_detail(config, port):
    """Pourquoi Odoo ne répond pas sur ce port, en une ligne."""
    where = f"{config.odoo_host}:{port}"
    if port == config.websocket_port:
        return (
            f"Odoo ne répond pas sur {where} (bus). Le bus n'écoute que si"
            " Odoo tourne avec workers >= 1.\n"
        )
    return f"Odoo ne répond pas sur {where} (web). Odoo est-il démarré ?\n"


async def _open_upstream(host, port):
    return await asyncio.open_connection(host, port)


async def handle(reader, writer, config):
    """Sert une connexion cliente : une requête, relayée puis fermée.

    Une ligne de journal par requête : client, méthode, cible, route (web
    ou bus), statut et durée — celle d'une WebSocket va jusqu'à sa fermeture.
    """
    started = time.monotonic()
    peer = writer.get_extra_info("peername")
    client_ip = peer[0] if peer else ""
    upstream_writer = None
    request = "-"
    route = "-"
    status = {"code": "?"}

    def journal():
        if config.log is not None:
            ms = int((time.monotonic() - started) * 1000)
            config.log(
                f"{client_ip} {request} → {route} {status['code']} {ms} ms"
            )

    try:
        try:
            head = await asyncio.wait_for(
                reader.readuntil(b"\r\n\r\n"), config.head_timeout
            )
        except asyncio.TimeoutError:
            await _reply_error(writer, 408, "Request Timeout")
            return
        except asyncio.LimitOverrunError:
            status["code"] = "431"
            await _reply_error(writer, 431, "Request Header Fields Too Large")
            journal()
            return
        except asyncio.IncompleteReadError:
            return
        try:
            method, target, version, headers = parse_head(head)
        except ValueError:
            status["code"] = "400"
            await _reply_error(writer, 400, "Bad Request")
            journal()
            return
        request = f"{method} {target}"
        bus = is_websocket_path(target, config)
        route = "bus" if bus else "web"
        port = config.websocket_port if bus else config.web_port
        try:
            upstream_reader, upstream_writer = await asyncio.wait_for(
                _open_upstream(config.odoo_host, port), config.connect_timeout
            )
        except asyncio.TimeoutError:
            status["code"] = "504"
            await _reply_error(
                writer,
                504,
                "Gateway Timeout",
                unreachable_detail(config, port),
            )
            journal()
            return
        except OSError:
            status["code"] = "502"
            await _reply_error(
                writer, 502, "Bad Gateway", unreachable_detail(config, port)
            )
            journal()
            return
        upstream_writer.write(
            rewrite_head(method, target, version, headers, client_ip, config)
        )

        def note_status(chunk):
            status["code"] = _status_of(chunk)

        # Ce que le client a déjà envoyé après la tête — un début de corps —
        # est dans le tampon du lecteur : _pipe le relaie en premier.
        to_client = asyncio.create_task(
            _pipe(
                upstream_reader, writer, half_close=False, on_first=note_status
            )
        )
        to_odoo = asyncio.create_task(
            _pipe(reader, upstream_writer, half_close=True)
        )
        # La fin de la réponse clôt l'échange ; un client qui ferme le premier
        # (onglet fermé, WebSocket quittée) le clôt aussi.
        done, _ = await asyncio.wait(
            {to_client, to_odoo}, return_when=asyncio.FIRST_COMPLETED
        )
        if to_odoo in done and not to_client.done():
            # Le client a fini d'envoyer : la réponse peut encore venir.
            await to_client
        for task in (to_client, to_odoo):
            task.cancel()
        journal()
    finally:
        for w in (upstream_writer, writer):
            if w is not None:
                w.close()


async def serve(config, listen, port, ssl_context=None):
    """Démarre l'écoute et rend le serveur asyncio, déjà à l'écoute.

    ssl_context : écoute en HTTPS ; Odoo, derrière, reste en HTTP clair.
    """
    return await asyncio.start_server(
        lambda r, w: handle(r, w, config),
        listen,
        port,
        limit=MAX_HEAD,
        ssl=ssl_context,
    )


def make_ssl_context(cert, key):
    """Contexte serveur TLS depuis un certificat et sa clé (PEM)."""
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(cert, key)
    return context


async def probe(config):
    """Tente une connexion aux deux ports d'Odoo.

    :return: {"web": bool, "bus": bool}, vrai quand le port accepte
    """
    result = {}
    for role, port in (
        ("web", config.web_port),
        ("bus", config.websocket_port),
    ):
        try:
            _, w = await asyncio.wait_for(
                _open_upstream(config.odoo_host, port), config.connect_timeout
            )
            w.close()
            result[role] = True
        except (OSError, asyncio.TimeoutError):
            result[role] = False
    return result


def startup_warnings(state, config):
    """Les avertissements à dire au démarrage d'après probe(), [] sinon."""
    warnings = []
    if not state.get("web"):
        warnings.append(unreachable_detail(config, config.web_port).strip())
    if not state.get("bus"):
        warnings.append(
            unreachable_detail(config, config.websocket_port).strip()
        )
    return warnings


def get_config(argv=None):
    parser = argparse.ArgumentParser(
        description=(
            "Mandataire inverse de développement devant Odoo : pages vers le"
            " port web, bus vers le port websocket. En production, préférer"
            " nginx (script/nginx/)."
        )
    )
    parser.add_argument(
        "--listen",
        default="127.0.0.1",
        help="Adresse d'écoute ; 0.0.0.0 pour l'exposer au réseau.",
    )
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--odoo-host", default="127.0.0.1")
    parser.add_argument("--web-port", type=int, default=8069)
    parser.add_argument(
        "--websocket-port",
        type=int,
        default=8072,
        help="Port du bus d'Odoo (gevent).",
    )
    parser.add_argument(
        "--websocket-path",
        action="append",
        help=(
            "Chemin routé vers le port du bus ; répétable. Défaut :"
            f" {', '.join(DEFAULT_WEBSOCKET_PATHS)}."
        ),
    )
    parser.add_argument(
        "--forwarded-proto",
        choices=("http", "https"),
        help=(
            "Valeur de X-Forwarded-Proto. Défaut : https avec --tls-cert,"
            " http sinon."
        ),
    )
    parser.add_argument(
        "--tls-cert",
        help="Certificat PEM : le mandataire écoute alors en HTTPS.",
    )
    parser.add_argument("--tls-key", help="Clé PEM du certificat.")
    parser.add_argument(
        "--trust-forwarded",
        action="store_true",
        help=(
            "Prolonger les X-Forwarded-* reçus au lieu de les remplacer, pour"
            " un mandataire placé derrière un autre. À éviter face à des"
            " navigateurs : ils pourraient se faire passer pour une autre"
            " adresse."
        ),
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Ne pas écrire une ligne par requête.",
    )
    args = parser.parse_args(argv)
    if bool(args.tls_cert) != bool(args.tls_key):
        parser.error("--tls-cert et --tls-key vont ensemble")
    return args


def config_from_args(args):
    return ProxyConfig(
        odoo_host=args.odoo_host,
        web_port=args.web_port,
        websocket_port=args.websocket_port,
        websocket_paths=tuple(args.websocket_path or DEFAULT_WEBSOCKET_PATHS),
        forwarded_proto=args.forwarded_proto
        or ("https" if args.tls_cert else "http"),
        trust_forwarded=args.trust_forwarded,
        log=None if args.quiet else print,
    )


async def _run(args):
    config = config_from_args(args)
    context = None
    if args.tls_cert:
        context = make_ssl_context(args.tls_cert, args.tls_key)
    server = await serve(config, args.listen, args.port, ssl_context=context)
    scheme = "https" if context else "http"
    print(
        f"Mandataire sur {scheme}://{args.listen}:{args.port} → pages"
        f" {config.odoo_host}:{config.web_port}, bus"
        f" {config.odoo_host}:{config.websocket_port}"
        f" ({', '.join(config.websocket_paths)})."
        " Odoo doit tourner avec proxy_mode = True."
    )
    for warning in startup_warnings(await probe(config), config):
        print(f"⚠️  {warning}")
    async with server:
        await server.serve_forever()


def main(argv=None):
    # Une ligne de journal doit paraître à sa requête, y compris quand la
    # sortie est un tube ou un fichier, que Python tamponne sinon par blocs.
    sys.stdout.reconfigure(line_buffering=True)
    try:
        asyncio.run(_run(get_config(argv)))
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
