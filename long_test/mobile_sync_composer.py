#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Les corps de référence du compositeur de messages, produits par Odoo 18.

Le compositeur de l'app reproduit le HTML que le navigateur envoie
(prettifyMessageContent de @mail/utils/common/format). Ce script fait
tourner LA fonction d'Odoo dans un Chromium sans écran : il ouvre une
session sur un Odoo 18, charge /odoo/discuss, puis évalue chaque cas de
composer-cases.json (les mentions retenues par getMentionsFromText du
service mail.store, comme au moment d'envoyer) et écrit
composer-golden.json à côté. La fonction tourne côté client : tout Odoo 18
du checkout donne les mêmes corps.

  ./long_test/mobile_sync_composer.py http://127.0.0.1:8069 admin admin \\
      --base ma_base
"""

import argparse
import http.cookies
import json
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from mobile_sync_cdp import Cdp  # noqa: E402
from mobile_sync_odoo import version_repondue  # noqa: E402

FIXTURES = (
    Path(__file__).resolve().parent.parent
    / "mobile"
    / "erplibre_home_mobile"
    / "src"
    / "__tests__"
    / "fixtures"
)
CAS = FIXTURES / "composer-cases.json"
REFERENCE = FIXTURES / "composer-golden.json"

MODULE_FORMAT = "@mail/utils/common/format"
# Les références sont celles d'Odoo 18 : un autre serveur n'en écrit pas
VERSION = 18
SORTIE_VERSION = 2

# Un cas dans la page : les choix de mentions de l'app (Mentions) mis à la
# forme des enregistrements d'Odoo, filtrés par getMentionsFromText, puis
# le corps de prettifyMessageContent
EVALUER_CAS = """
(async (cas) => {
    const { prettifyMessageContent } = odoo.loader.modules.get(%s);
    const store = odoo.__WOWL_DEBUG__.root.env.services["mail.store"];
    const choix = cas.mentions || { partners: [], channels: [] };
    const valides = store.getMentionsFromText(cas.text, {
        mentionedPartners: choix.partners.map((p) => ({ id: p.id, name: p.name })),
        mentionedChannels: choix.channels.map((c) => ({
            id: c.id,
            displayName: c.name,
            parent_channel_id: c.parentName ? { displayName: c.parentName } : false,
        })),
    });
    const body = await prettifyMessageContent(cas.text, valides);
    return {
        name: cas.name,
        body: String(body),
        partnerIds: valides.partners.map((p) => p.id),
        specialMentions: valides.specialMentions,
    };
})(%s)
"""


def parser():
    parseur = argparse.ArgumentParser(
        description="Les corps de référence du compositeur, par Odoo 18."
    )
    parseur.add_argument("url", help="l'Odoo 18, ex. http://127.0.0.1:8069")
    parseur.add_argument("login")
    parseur.add_argument("password")
    parseur.add_argument(
        "--base", help="la base ; sans elle, la seule que liste le serveur"
    )
    parseur.add_argument("--chromium", default="/usr/bin/chromium")
    return parseur


def jsonrpc(url, params, cookie=None):
    """Un appel JSON-RPC : (résultat, en-têtes de la réponse)."""
    requete = urllib.request.Request(
        url,
        data=json.dumps(
            {"jsonrpc": "2.0", "method": "call", "params": params}
        ).encode(),
        headers={"Content-Type": "application/json"},
    )
    if cookie:
        requete.add_header("Cookie", cookie)
    with urllib.request.urlopen(requete, timeout=30) as reponse:
        corps = json.load(reponse)
        if "error" in corps:
            raise RuntimeError(f"{url} : {corps['error'].get('message')}")
        return corps["result"], reponse.headers


def base_unique(url):
    """La base du serveur quand il n'en liste qu'une."""
    bases, _ = jsonrpc(f"{url}/web/database/list", {})
    if len(bases) != 1:
        raise RuntimeError(f"--base requis : le serveur liste {bases}")
    return bases[0]


def session(url, base, login, password):
    """Le cookie session_id d'une session ouverte par
    /web/session/authenticate."""
    resultat, entetes = jsonrpc(
        f"{url}/web/session/authenticate",
        {"db": base, "login": login, "password": password},
    )
    if not resultat or not resultat.get("uid"):
        raise RuntimeError(f"connexion refusée pour {login}")
    for entete in entetes.get_all("Set-Cookie") or []:
        biscuit = http.cookies.SimpleCookie(entete)
        if "session_id" in biscuit:
            return biscuit["session_id"].value
    raise RuntimeError("la réponse ne pose aucun cookie session_id")


def port_libre():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def demarrer_chromium(chemin, port, profil, attente=30):
    """Chromium sans écran, son port devtools ouvert, une page vide ; rend
    le processus quand /json répond."""
    processus = subprocess.Popen(
        [
            chemin,
            "--headless=new",
            f"--remote-debugging-port={port}",
            f"--user-data-dir={profil}",
            "--no-first-run",
            "--no-default-browser-check",
            "about:blank",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    fin = time.monotonic() + attente
    while time.monotonic() < fin:
        if processus.poll() is not None:
            break
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/json", timeout=2)
            return processus
        except OSError:
            time.sleep(0.3)
    processus.kill()
    raise RuntimeError(f"{chemin} n'ouvre pas son port devtools {port}")


def references(cdp, url, cookie, cas):
    """Les corps d'Odoo pour chaque cas, dans l'ordre des cas."""
    cdp.envoyer(
        "Network.setCookie",
        {"name": "session_id", "value": cookie, "url": url},
    )
    cdp.envoyer("Page.navigate", {"url": f"{url}/odoo/discuss"})
    cdp.attendre(
        "!!(window.odoo && odoo.loader"
        f" && odoo.loader.modules.get({json.dumps(MODULE_FORMAT)})"
        " && odoo.__WOWL_DEBUG__"
        ' && odoo.__WOWL_DEBUG__.root.env.services["mail.store"])',
        delai=120,
    )
    return [
        cdp.evaluer(
            EVALUER_CAS
            % (
                json.dumps(MODULE_FORMAT),
                json.dumps(un_cas, ensure_ascii=False),
            )
        )
        for un_cas in cas
    ]


def main(argv=None):
    args = parser().parse_args(argv)
    url = args.url.rstrip("/")
    majeure = version_repondue(url, delai=10)
    if majeure != VERSION:
        print(
            f"{url} répond Odoo {majeure} et non {VERSION} :"
            " aucune référence écrite"
        )
        return SORTIE_VERSION
    base = args.base or base_unique(url)
    cookie = session(url, base, args.login, args.password)
    cas = json.loads(CAS.read_text())
    port = port_libre()
    profil = tempfile.mkdtemp(prefix="composer_chromium_")
    processus = demarrer_chromium(args.chromium, port, profil)
    cdp = None
    try:
        cdp = Cdp(port)
        sortie = references(cdp, url, cookie, cas)
    finally:
        if cdp:
            cdp.fermer()
        processus.terminate()
        try:
            processus.wait(timeout=10)
        except subprocess.TimeoutExpired:
            processus.kill()
        shutil.rmtree(profil, ignore_errors=True)
    REFERENCE.write_text(
        json.dumps(sortie, ensure_ascii=False, indent=2) + "\n"
    )
    print(f"{len(sortie)} corps écrits dans {REFERENCE}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
