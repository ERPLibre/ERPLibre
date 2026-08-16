#!/usr/bin/env python3
# © 2021-2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Request every public URL of a migrated database, and report what breaks.

Why this exists
---------------
A migration can finish, load every module, and still serve a 500 on a page
nobody thought to open. Measured on a real one: ``/blog/<blog>/post/<post>``
answered 500 because a COW copy frozen on the previous version no longer held
the section a child view xpaths into. Nothing in the migration log said so —
the module loading had succeeded.

Where the list comes from
-------------------------
``/sitemap.xml``: the list Odoo itself publishes for search engines, built by
``website.enumerate_pages()``. It covers the controller routes declared with
``sitemap=True`` and the records behind them — pages, blog posts, products.

It cannot be read from ``odoo-bin shell``: ``enumerate_pages()`` asks for
``http.root.get_db_router(request.db)`` and raises « object unbound » without
a real request. So the server is started, asked, and stopped.

What counts as a failure
------------------------
Any status >= 400. The sitemap is the PUBLIC list: a page listed there and
answering 403 or 404 is as wrong as one answering 500, just less loud.

Exit codes: 0 every URL answered, 1 some failed, 2 the tool failed.
"""

import argparse
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

sys.path.append(
    os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
)

try:
    from script.todo.todo_i18n import t
except Exception:  # pragma: no cover - repli si i18n indisponible

    def t(key: str) -> str:
        return key


RE_LOC = re.compile(r"<loc>\s*([^<\s]+)\s*</loc>", re.I)

# Un port à part : la migration tourne souvent à côté d'une instance vivante,
# et lui voler 8069 ferait échouer le test pour une raison sans rapport.
DEFAULT_PORT = 8169


def start_server(database, port, config_path="./config.conf"):
    """Démarrer Odoo sur la base, sans écrire dans le terminal appelant."""
    return subprocess.Popen(
        [
            "./run.sh",
            "-c",
            config_path,
            "-d",
            database,
            "--http-port",
            str(port),
            "--log-level=warn",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )


def fetch(url, timeout=30):
    """(statut, corps). Statut 0 quand la connexion elle-même échoue."""
    try:
        with urllib.request.urlopen(url, timeout=timeout) as answer:
            return answer.getcode(), answer.read().decode(
                "utf-8", errors="replace"
            )
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", errors="replace")
    except Exception:
        return 0, ""


def wait_ready(base_url, timeout=180, sleep=2):
    """Attendre que le serveur réponde. False s'il n'est jamais venu."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        status, _body = fetch(base_url + "/web/login", timeout=5)
        if status:
            return True
        time.sleep(sleep)
    return False


def sitemap_urls(base_url):
    """Les URL du sitemap, index compris, ramenées sur l'hôte local.

    Le sitemap porte le domaine du site (technolibre.ca) ; on teste une base
    servie en local. Garder le domaine ferait interroger la production —
    c'est le genre d'erreur qui ne se voit qu'après.
    """
    status, body = fetch(base_url + "/sitemap.xml")
    if not status or status >= 400:
        return [], status
    lst_loc = RE_LOC.findall(body)
    # Un index de sitemaps ne contient que des sitemaps : on descend d'un cran.
    if "<sitemapindex" in body.lower():
        lst_page = []
        for loc in lst_loc:
            _status, sub = fetch(local_url(base_url, loc))
            lst_page.extend(RE_LOC.findall(sub))
        lst_loc = lst_page
    seen, lst_url = set(), []
    for loc in lst_loc:
        url = local_url(base_url, loc)
        if url not in seen:
            seen.add(url)
            lst_url.append(url)
    return lst_url, status


def local_url(base_url, loc):
    """Remplacer le schéma et l'hôte du sitemap par ceux qu'on teste."""
    parsed = urllib.parse.urlparse(loc)
    path = parsed.path or "/"
    if parsed.query:
        path += "?" + parsed.query
    return base_url.rstrip("/") + path


def check_urls(lst_url, timeout=30):
    """[(url, statut)] pour celles qui ont échoué."""
    lst_failure = []
    for url in lst_url:
        status, _body = fetch(url, timeout=timeout)
        if status == 0 or status >= 400:
            lst_failure.append((url, status))
    return lst_failure


def render(lst_url, lst_failure):
    if not lst_url:
        return f"⚠️ {t('The sitemap listed no URL: nothing was tested.')}\n"
    if not lst_failure:
        return (
            f"✅ -> {len(lst_url)} {t('public URL(s) answered without error.')}"
            "\n"
        )
    lines = [
        f"❌ {len(lst_failure)} {t('of')} {len(lst_url)}"
        f" {t('public URL(s) failed')} :"
    ]
    for url, status in lst_failure:
        label = status or t("no answer")
        lines.append(f"   [{label}] {url}")
    lines.append(
        f"   {t('A page listed for search engines that does not answer is')}"
        f" {t('a page your visitors do not reach either.')}"
    )
    return "\n".join(lines) + "\n"


def run(database, port, config_path, limit=None, timeout=30, boot=180):
    """Démarrer, interroger, arrêter. Rend (urls, échecs)."""
    base_url = f"http://127.0.0.1:{port}"
    server = start_server(database, port, config_path)
    try:
        if not wait_ready(base_url, timeout=boot):
            raise RuntimeError(
                f"{t('The server never answered on')} {base_url}"
            )
        lst_url, status = sitemap_urls(base_url)
        if not status:
            raise RuntimeError(f"{t('Could not read')} {base_url}/sitemap.xml")
        if limit:
            lst_url = lst_url[:limit]
        return lst_url, check_urls(lst_url, timeout=timeout)
    finally:
        server.terminate()
        try:
            server.wait(timeout=30)
        except subprocess.TimeoutExpired:
            server.kill()


def main(argv=None):
    parser = argparse.ArgumentParser(
        description=(
            "Start Odoo on a database, request every URL of its sitemap, and"
            " report those that fail."
        )
    )
    parser.add_argument("-d", "--database", required=True)
    parser.add_argument("-c", "--config", default="./config.conf")
    parser.add_argument("-p", "--port", type=int, default=DEFAULT_PORT)
    parser.add_argument(
        "--limit", type=int, default=None, help="test only the first N URLs"
    )
    parser.add_argument("--timeout", type=int, default=30)
    parser.add_argument(
        "--boot-timeout",
        type=int,
        default=180,
        help="how long to wait for the server to answer",
    )
    config = parser.parse_args(argv)

    print(
        f"⧖ {t('Starting Odoo on')} '{config.database}'"
        f" ({t('port')} {config.port})…"
    )
    try:
        lst_url, lst_failure = run(
            config.database,
            config.port,
            config.config,
            limit=config.limit,
            timeout=config.timeout,
            boot=config.boot_timeout,
        )
    except RuntimeError as exc:
        print(f"❌ {exc}")
        return 2
    print(render(lst_url, lst_failure))
    return 1 if lst_failure else 0


if __name__ == "__main__":
    sys.exit(main())
