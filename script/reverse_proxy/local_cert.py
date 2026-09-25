#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Certificats TLS locaux pour tester le mandataire inverse en HTTPS.

Deux étages, comme un vrai déploiement : une autorité locale (ca.crt), à
importer UNE fois dans le navigateur, et un certificat serveur qu'elle signe
pour les noms et adresses de ce poste. L'autorité se garde d'une émission à
l'autre, si bien qu'ajouter un nom ne fait pas réapparaître l'alerte du
navigateur ; seul le certificat serveur est refait.

Le répertoire est en 0700 et les clés en 0600 : une autorité importée peut
signer pour n'importe quel nom, et quiconque lit ca.key peut se faire
passer pour n'importe quel site auprès de ce navigateur.

Tout passe par la commande openssl, présente sur les systèmes pris en
charge ; aucune dépendance Python n'est ajoutée.
"""

import argparse
import ipaddress
import os
import socket
import subprocess
import sys
import tempfile

DEFAULT_DIR = os.path.join(
    os.path.expanduser("~/.erplibre"), "reverse_proxy_tls"
)

CA_DAYS = 3650
# Les navigateurs refusent un certificat serveur valide plus de 398 jours.
SERVER_DAYS = 397


def paths(directory):
    """Les quatre fichiers du répertoire, par rôle."""
    return {
        "ca_crt": os.path.join(directory, "ca.crt"),
        "ca_key": os.path.join(directory, "ca.key"),
        "server_crt": os.path.join(directory, "server.crt"),
        "server_key": os.path.join(directory, "server.key"),
    }


def exists(directory):
    """Vrai quand le certificat serveur et sa clé sont en place."""
    p = paths(directory)
    return os.path.isfile(p["server_crt"]) and os.path.isfile(p["server_key"])


def default_names():
    """localhost, les boucles locales, le nom d'hôte et ses adresses IPv4.

    Un nom qui ne se résout pas est simplement omis : le certificat reste
    valide pour les autres.
    """
    names = ["localhost", "127.0.0.1", "::1"]
    host = socket.gethostname()
    if host:
        names.append(host)
    try:
        infos = socket.getaddrinfo(host, None, socket.AF_INET)
    except OSError:
        infos = []
    for info in infos:
        names.append(info[4][0])
    try:
        out = subprocess.run(
            ["ip", "-o", "-4", "addr", "show"],
            capture_output=True,
            text=True,
            timeout=5,
        ).stdout
    except (OSError, subprocess.SubprocessError):
        out = ""
    for line in out.splitlines():
        parts = line.split()
        if "inet" in parts:
            names.append(parts[parts.index("inet") + 1].split("/")[0])
    unique = []
    for name in names:
        if name not in unique:
            unique.append(name)
    return unique


def _san(names):
    """subjectAltName : IP pour une adresse, DNS pour un nom."""
    entries = []
    for name in names:
        try:
            ipaddress.ip_address(name)
            entries.append(f"IP:{name}")
        except ValueError:
            entries.append(f"DNS:{name}")
    return ",".join(entries)


def _openssl(*args):
    subprocess.run(
        ["openssl", *args], check=True, capture_output=True, text=True
    )


def _private(path):
    os.chmod(path, 0o600)


def issue(directory, names):
    """Émet le certificat serveur pour `names`, et l'autorité s'il le faut.

    :param directory: répertoire des certificats, créé en 0700 au besoin
    :param names: noms DNS et adresses IP que le certificat doit couvrir
    :return: paths(directory)
    :raises subprocess.CalledProcessError: openssl a refusé une étape
    """
    os.makedirs(directory, mode=0o700, exist_ok=True)
    os.chmod(directory, 0o700)
    p = paths(directory)
    if not (os.path.isfile(p["ca_crt"]) and os.path.isfile(p["ca_key"])):
        _openssl(
            "req", "-x509", "-newkey", "rsa:2048", "-nodes",
            "-keyout", p["ca_key"], "-out", p["ca_crt"],
            "-days", str(CA_DAYS),
            "-subj", "/CN=ERPLibre local test CA",
            "-addext", "basicConstraints=critical,CA:TRUE,pathlen:0",
            "-addext", "keyUsage=critical,keyCertSign,cRLSign",
        )  # fmt: skip
        _private(p["ca_key"])
    with tempfile.TemporaryDirectory() as tmp:
        csr = os.path.join(tmp, "server.csr")
        ext = os.path.join(tmp, "server.ext")
        with open(ext, "w", encoding="utf-8") as f:
            f.write(
                "basicConstraints=critical,CA:FALSE\n"
                "keyUsage=critical,digitalSignature,keyEncipherment\n"
                "extendedKeyUsage=serverAuth\n"
                f"subjectAltName={_san(names)}\n"
            )
        _openssl(
            "req", "-newkey", "rsa:2048", "-nodes",
            "-keyout", p["server_key"], "-out", csr,
            "-subj", f"/CN={names[0]}",
        )  # fmt: skip
        _private(p["server_key"])
        _openssl(
            "x509", "-req", "-in", csr,
            "-CA", p["ca_crt"], "-CAkey", p["ca_key"], "-CAcreateserial",
            "-out", p["server_crt"], "-days", str(SERVER_DAYS),
            "-extfile", ext,
        )  # fmt: skip
    serial = os.path.join(directory, "ca.srl")
    if os.path.exists(serial):
        _private(serial)
    return p


def main(argv=None):
    parser = argparse.ArgumentParser(
        description=(
            "Certificats TLS locaux pour tester le mandataire inverse en"
            " HTTPS : une autorité à importer dans le navigateur, et un"
            " certificat serveur qu'elle signe."
        )
    )
    parser.add_argument("--dir", default=DEFAULT_DIR)
    parser.add_argument(
        "--name",
        action="append",
        help="Nom ou adresse de plus à couvrir ; répétable.",
    )
    args = parser.parse_args(argv)
    names = default_names() + [
        n for n in (args.name or []) if n not in default_names()
    ]
    p = issue(args.dir, names)
    print(f"Autorité  : {p['ca_crt']}")
    print(f"Serveur   : {p['server_crt']}")
    print(f"Clé       : {p['server_key']}")
    print(f"Noms      : {', '.join(names)}")
    print(
        "Importer l'autorité une fois dans le navigateur (Firefox :"
        " Paramètres › Certificats › Autorités › Importer)."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
