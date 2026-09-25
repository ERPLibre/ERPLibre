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
import sys
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


@dataclass(frozen=True)
class ProxyConfig:
    odoo_host: str = "127.0.0.1"
    web_port: int = 8069
    websocket_port: int = 8072
    websocket_paths: tuple = DEFAULT_WEBSOCKET_PATHS
    forwarded_proto: str = "http"


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
    upgrade_value = next((v for n, v in headers if n.lower() == "upgrade"), "")
    host = next((v for n, v in headers if n.lower() == "host"), "")
    kept = [
        (n, v)
        for n, v in headers
        if n.lower() not in HOP_BY_HOP and n.lower() not in FORWARDED
    ]
    kept += [
        ("X-Forwarded-For", client_ip),
        ("X-Real-IP", client_ip),
        ("X-Forwarded-Host", host),
        ("X-Forwarded-Proto", config.forwarded_proto),
    ]
    if upgrade:
        kept += [("Upgrade", upgrade_value), ("Connection", "Upgrade")]
    else:
        kept.append(("Connection", "close"))
    lines = [f"{method} {target} {version}"]
    lines += [f"{n}: {v}" for n, v in kept]
    return ("\r\n".join(lines) + "\r\n\r\n").encode("latin-1")


async def _reply_error(writer, status, reason):
    body = f"{status} {reason}\n".encode()
    writer.write(
        f"HTTP/1.1 {status} {reason}\r\nContent-Type: text/plain\r\n"
        f"Content-Length: {len(body)}\r\nConnection: close\r\n\r\n".encode()
        + body
    )
    try:
        await writer.drain()
    except ConnectionError:
        pass


async def _pipe(reader, writer, half_close):
    """Copie reader vers writer jusqu'à la fin du flux.

    half_close : à la fin, fermer seulement l'écriture (write_eof) plutôt que
    rien — le client qui a fini d'envoyer attend encore la réponse.
    """
    try:
        while data := await reader.read(RELAY_CHUNK):
            writer.write(data)
            await writer.drain()
        if half_close and writer.can_write_eof():
            writer.write_eof()
    except (ConnectionError, OSError):
        pass


async def handle(reader, writer, config):
    """Sert une connexion cliente : une requête, relayée puis fermée."""
    peer = writer.get_extra_info("peername")
    client_ip = peer[0] if peer else ""
    upstream_writer = None
    try:
        try:
            head = await reader.readuntil(b"\r\n\r\n")
        except asyncio.LimitOverrunError:
            await _reply_error(writer, 431, "Request Header Fields Too Large")
            return
        except asyncio.IncompleteReadError:
            return
        try:
            method, target, version, headers = parse_head(head)
        except ValueError:
            await _reply_error(writer, 400, "Bad Request")
            return
        port = (
            config.websocket_port
            if is_websocket_path(target, config)
            else config.web_port
        )
        try:
            upstream_reader, upstream_writer = await asyncio.open_connection(
                config.odoo_host, port
            )
        except OSError as e:
            print(f"Odoo injoignable sur {config.odoo_host}:{port} : {e}")
            await _reply_error(writer, 502, "Bad Gateway")
            return
        upstream_writer.write(
            rewrite_head(method, target, version, headers, client_ip, config)
        )
        # Ce que le client a déjà envoyé après la tête — un début de corps —
        # est dans le tampon du lecteur : _pipe le relaie en premier.
        to_client = asyncio.create_task(
            _pipe(upstream_reader, writer, half_close=False)
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
    finally:
        for w in (upstream_writer, writer):
            if w is not None:
                w.close()


async def serve(config, listen, port):
    """Démarre l'écoute et rend le serveur asyncio, déjà à l'écoute."""
    return await asyncio.start_server(
        lambda r, w: handle(r, w, config), listen, port, limit=MAX_HEAD
    )


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
        default="http",
        choices=("http", "https"),
        help="Valeur de X-Forwarded-Proto, https derrière une terminaison TLS.",
    )
    return parser.parse_args(argv)


def config_from_args(args):
    return ProxyConfig(
        odoo_host=args.odoo_host,
        web_port=args.web_port,
        websocket_port=args.websocket_port,
        websocket_paths=tuple(args.websocket_path or DEFAULT_WEBSOCKET_PATHS),
        forwarded_proto=args.forwarded_proto,
    )


async def _run(args):
    config = config_from_args(args)
    server = await serve(config, args.listen, args.port)
    print(
        f"Mandataire sur {args.listen}:{args.port} → pages"
        f" {config.odoo_host}:{config.web_port}, bus"
        f" {config.odoo_host}:{config.websocket_port}"
        f" ({', '.join(config.websocket_paths)})."
        " Odoo doit tourner avec proxy_mode = True."
    )
    async with server:
        await server.serve_forever()


def main(argv=None):
    try:
        asyncio.run(_run(get_config(argv)))
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
