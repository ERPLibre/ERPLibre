# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Sonder une machine, locale ou par SSH, et classer sa réponse.

La sonde est un script sh propre à chaque ERP, envoyé sur stdin : un
aller-retour par hôte, rien à installer de l'autre côté. Sa sortie commence
par une ligne d'en-tête « <EN-TÊTE>\\t<statut> », puis une ligne par
trouvaille, champs séparés par des tabulations : « INSTALL\\t... » dans
l'ordre des champs que l'ERP déclare, « CONTAINER\\t... » dans l'ordre de
CONTAINER_FIELDS. Ce qui précède l'en-tête (bannière de l'hôte) est ignoré.

Chaque hôte finit dans un état qui dit quoi faire : ok, auth (clé refusée),
hostkey (clé d'hôte inconnue ou changée), net (injoignable) ou error (la
sonde n'a pas répondu). Le rapport de l'ERP `erp` est écrit sous
private/<erp>/inventory/<hôte>.json (0600, dossier 0700) : il nomme des
machines et des bases, il ne quitte pas private/.
"""

import datetime
import json
import os
import re
import shlex
import subprocess

DEFAULT_DEPTH = 7

CONTAINER_FIELDS = ("engine", "name", "image", "state")

# Ce que ssh écrit quand il n'atteint pas la sonde, par cause.
_SSH_FAILURES = (
    ("hostkey", ("Host key verification failed",)),
    ("auth", ("Permission denied (",)),
    (
        "net",
        (
            "Could not resolve hostname",
            "Connection timed out",
            "Connection refused",
            "No route to host",
            "Network is unreachable",
            "timeout",
        ),
    ),
)

# Un nom d'hôte ou d'alias, tel qu'il devient un nom de fichier.
_SAFE = re.compile(r"[^A-Za-z0-9._-]")

# État d'un hôte -> libellé affiché (clé i18n).
STATE_LABELS = {
    "ok": "reached",
    "auth": "key refused: check the SSH key of this host",
    "hostkey": "unknown or changed host key: connect once by hand",
    "net": "unreachable",
    "error": "the probe did not answer",
}


def inventory_dir(erp):
    """private/<erp>/inventory, relatif à la racine du dépôt."""
    return os.path.join("private", erp, "inventory")


def _header_index(header, lines):
    """Indice de la ligne d'en-tête « <header>\\t... », ou None."""
    for i, line in enumerate(lines):
        if line.startswith(header + "\t"):
            return i
    return None


def parse_probe(header, install_fields, text):
    """{status, installs, containers} de la sortie de la sonde, ou None
    sans ligne d'en-tête `header`.

    Une ligne trop courte est complétée par des chaînes vides ; une ligne
    d'un autre genre qu'INSTALL ou CONTAINER est ignorée.
    """
    lines = (text or "").splitlines()
    i = _header_index(header, lines)
    if i is None:
        return None
    report = {"status": lines[i].split("\t", 1)[1].strip()}
    report["installs"], report["containers"] = [], []
    for line in lines[i + 1 :]:
        kind, _tab, rest = line.partition("\t")
        if kind == "INSTALL":
            fields = install_fields
            target = report["installs"]
        elif kind == "CONTAINER":
            fields = CONTAINER_FIELDS
            target = report["containers"]
        else:
            continue
        values = rest.split("\t")
        values += [""] * (len(fields) - len(values))
        target.append(dict(zip(fields, values)))
    return report


def classify(header, code, output):
    """ok, auth, hostkey, net ou error : pourquoi un hôte a (ou n'a pas)
    répondu. ok dès que l'en-tête `header` figure dans la sortie, quel que
    soit le code."""
    if _header_index(header, (output or "").splitlines()) is not None:
        return "ok"
    for kind, marks in _SSH_FAILURES:
        if any(mark in (output or "") for mark in marks):
            return kind
    return "error"


def remote_argv(host, roots, depth=DEFAULT_DEPTH):
    """ssh qui lance la sonde reçue sur stdin, sans terminal ni question."""
    from script.proxmox import proxmox_deploy

    remote = " ".join(
        ["sh", "-s", "--", str(depth)] + [shlex.quote(r) for r in roots]
    )
    return proxmox_deploy.ssh_argv(host, remote)


def run_probe(probe, argv, timeout=300):
    """(code, sortie) du script `probe` envoyé sur stdin à `argv`.

    255 et la cause quand la commande dépasse `timeout` ou ne se lance pas ;
    le bruit de connexion de ssh est retiré de la sortie.
    """
    from script.proxmox import proxmox_deploy

    with open(probe, encoding="utf-8") as f:
        script = f.read()
    try:
        r = subprocess.run(
            argv, input=script, capture_output=True, text=True, timeout=timeout
        )
    except subprocess.TimeoutExpired:
        return 255, "timeout"
    except OSError as e:
        return 255, str(e)
    return r.returncode, proxmox_deploy.strip_ssh_noise(
        (r.stdout or "") + (r.stderr or "")
    )


def save(erp, root, host, state, report, now=None):
    """Écrit le rapport de `host` en 0600 sous private/<erp>/inventory/ ;
    rend son chemin. Le nom d'hôte, assaini, ne sort pas du dossier."""
    directory = os.path.join(root, inventory_dir(erp))
    os.makedirs(directory, mode=0o700, exist_ok=True)
    path = os.path.join(directory, _SAFE.sub("_", host) + ".json")
    data = {
        "host": host,
        "state": state,
        "date": (now or datetime.datetime.now()).isoformat(timespec="seconds"),
        "report": report,
    }
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(json.dumps(data, indent=4, sort_keys=True) + "\n")
    return path
