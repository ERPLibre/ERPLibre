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
import signal
import socket
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


def can_ask():
    """Peut-on poser une question ICI ?

    Il faut deux choses, pas une : de quoi LIRE la réponse (stdin sur un
    terminal) et de quoi MONTRER la question (stdout aussi). Ne tester que
    stdin laisse poser une invite qui part dans un tube : elle reste en
    tampon, invisible, pendant que le processus attend — on croit à un
    blocage et l'on tape Entrée à l'aveugle.
    """
    return sys.stdin.isatty() and sys.stdout.isatty()


RE_LOC = re.compile(r"<loc>\s*([^<\s]+)\s*</loc>", re.I)

# « [view_id: 3282, xml_id: n/a, model: n/a, parent_id: 3281] ». Seule la
# phrase qui précède est traduite ; cette ligne-ci ne l'est pas, donc la lire
# marche dans les deux langues. Le PARENT est le coupable : c'est la copie
# figée dans laquelle l'enfant ne trouve plus son xpath.
RE_CONTEXT = re.compile(r"\[view_id: (\d+),.*?parent_id: (\d+)\]")

# Un port à part : la migration tourne souvent à côté d'une instance vivante,
# et lui voler 8069 ferait échouer le test pour une raison sans rapport.
DEFAULT_PORT = 8169


def run_psql(database, sql):
    """Lecture seule, garantie par le serveur PostgreSQL lui-même."""
    env = os.environ.copy()
    env["PGOPTIONS"] = "-c default_transaction_read_only=on"
    env["PSQLRC"] = ""
    done = subprocess.run(
        ["psql", "-X", "-w", "-d", database, "-tAF", "\x1f", "-c", sql],
        capture_output=True,
        text=True,
        env=env,
    )
    if done.returncode:
        return []
    return [line.split("\x1f") for line in done.stdout.splitlines() if line]


def start_server(database, port, config_path="./config.conf", log_path=None):
    """Démarrer Odoo, son journal dans un FICHIER.

    Pas un tube : Python bufferise par blocs quand sa sortie n'est pas un
    terminal, et un fil de lecture court alors après des lignes qui n'ont
    pas encore été écrites. Mesuré — 24 lignes vues sur 198, et la trace qui
    nomme la vue fautive faisait partie des absentes. Un fichier se relit
    entièrement, quand on veut.
    """
    handle = open(log_path, "w", encoding="utf-8") if log_path else None
    server = subprocess.Popen(
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
        stdout=handle or subprocess.DEVNULL,
        stderr=subprocess.STDOUT,
        text=True,
        # Son propre groupe de processus : « ./run.sh » est un script bash
        # qui ne transmet rien à son enfant. Un terminate() sur lui tuait le
        # script et laissait odoo-bin vivant, tenant le port. L'essai suivant
        # démarrait alors un serveur qui ne pouvait pas se lier, et
        # interrogeait sans le savoir CELUI D'AVANT — mesuré, deux fois.
        start_new_session=True,
    )
    server.erplibre_log = handle
    return server


def read_log(log_path):
    """Le journal du serveur, tel qu'écrit jusqu'ici."""
    if not log_path or not os.path.isfile(log_path):
        return []
    with open(log_path, "r", encoding="utf-8", errors="replace") as handle:
        return handle.read().splitlines()


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


# Odoo écrit sa trace APRÈS avoir répondu, et par le tube d'un script shell :
# mesuré, elle peut arriver près de trois secondes plus tard. Une demi-seconde
# concluait « aucune vue en cause » sur des pages qui en nommaient une.
LOG_DELAY = 3.0


def attach_missing_parents(lst_failure, lst_log):
    """Repêcher les contextes arrivés trop tard pour leur tranche.

    Le découpage par URL est une commodité, pas une garantie : le journal est
    asynchrone. Ce second passage lit TOUT ce qui a été capturé et rattache
    ce qui n'avait été rattaché à rien — mieux vaut un coupable mal attribué
    qu'un coupable perdu.
    """
    known = {pid for _u, _s, lst in lst_failure for pid in lst}
    extra = []
    for line in lst_log:
        for _view_id, parent_id in RE_CONTEXT.findall(line):
            if parent_id not in known and parent_id not in extra:
                extra.append(parent_id)
    if not extra:
        return lst_failure
    rebuilt = []
    placed = False
    for url, status, lst_parent in lst_failure:
        if not lst_parent and not placed:
            lst_parent = list(extra)
            placed = True
        rebuilt.append((url, status, lst_parent))
    if not placed and rebuilt:
        url, status, lst_parent = rebuilt[0]
        rebuilt[0] = (url, status, lst_parent + extra)
    return rebuilt


def check_urls(lst_url, timeout=30):
    """[(url, statut, [])] pour celles qui ont échoué.

    Les vues en cause sont rattachées après coup, en relisant le journal du
    serveur : elles y arrivent quand Odoo vide son tampon, pas quand la
    requête revient.
    """
    lst_failure = []
    for url in lst_url:
        status, _body = fetch(url, timeout=timeout)
        if status == 0 or status >= 400:
            lst_failure.append((url, status, []))
    return lst_failure


def culprit_keys(database, lst_failure):
    """Les clés des vues parentes mises en cause, sans doublon.

    C'est ce qu'on passe à reset_stale_cow_views : il travaille par clé, et
    relever un identifiant dans une trace pour le traduire à la main est
    exactement la recopie où l'on se trompe.
    """
    lst_id = []
    for _url, _status, lst_parent in lst_failure:
        for parent_id in lst_parent:
            if parent_id not in lst_id:
                lst_id.append(parent_id)
    if not lst_id:
        return []
    ids = ",".join(str(int(x)) for x in lst_id)
    rows = run_psql(
        database,
        f"SELECT id, key, website_id FROM ir_ui_view WHERE id IN ({ids})"
        " AND key IS NOT NULL ORDER BY id;",
    )
    lst_key = []
    for row in rows:
        if len(row) >= 2 and row[1] and row[1] not in lst_key:
            lst_key.append(row[1])
    return lst_key


def render(lst_url, lst_failure, lst_key=None):
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
    for url, status, lst_parent in lst_failure:
        label = status or t("no answer")
        lines.append(f"   [{label}] {url}")
        if lst_parent:
            lines.append(
                f"       {t('parent view(s) in cause')} :"
                f" {', '.join(lst_parent)}"
            )
    if lst_key:
        lines.append(
            f"   {t('Those parents are copies frozen on an older version;')}"
            f" {t('resetting them onto the module view is the fix')} :"
        )
        for key in lst_key:
            lines.append(f"       {key}")
    lines.append(
        f"   {t('A page listed for search engines that does not answer is')}"
        f" {t('a page your visitors do not reach either.')}"
    )
    return "\n".join(lines) + "\n"


def apply_reset(database, lst_key):
    """Réinitialiser ces copies sur leur vue module. ÉCRIT en base.

    On délègue à reset_stale_cow_views : il sauvegarde l'arch précédente
    avant d'écrire, et c'est déjà lui qu'on documente partout ailleurs. En
    refaire une seconde version ici, c'est se donner deux comportements à
    tenir d'accord.
    """
    cmd = [
        sys.executable,
        os.path.join(
            "script", "odoo", "migration", "reset_stale_cow_views.py"
        ),
        "-d",
        database,
    ]
    for key in lst_key:
        cmd += ["--reset", key]
    cmd.append("--apply")
    done = subprocess.run(cmd, capture_output=True, text=True)
    return done.returncode, done.stdout + done.stderr


def prompt(database, lst_failure, lst_key, ask=input):
    """Proposer de corriger, puis dire ce qu'il reste. Rend les clés traitées.

    Détecter sans offrir le geste, c'est laisser relever des identifiants
    dans une trace pour les traduire en clés à la main — au moment précis où
    l'on veut juste que la page réponde.
    """
    if not lst_key:
        print(f"ℹ -> {t('No parent view named: nothing to offer.')}")
        return []
    print(f"\n✨ {t('Copies to reset onto their module view')} :")
    for index, key in enumerate(lst_key, start=1):
        print(f"   [{index}] {key}")
    print(f"   [a] {t('All of the list above')}")
    answer = (
        ask(
            f"💬 {t('Which one(s) to reset?')}"
            f" ({t('numbers separated by commas, a = all, empty =')}"
            f" {t('nothing')}) : "
        )
        .strip()
        .lower()
    )
    if not answer:
        print(f"ℹ -> {t('Kept. Nothing was reset.')}")
        return []
    if answer == "a":
        lst_chosen = list(lst_key)
    else:
        lst_chosen = []
        for part in answer.replace(" ", "").split(","):
            if part.isdigit() and 1 <= int(part) <= len(lst_key):
                lst_chosen.append(lst_key[int(part) - 1])
        if not lst_chosen:
            print(f"⚠️ {t('Unknown choice, nothing was reset.')}")
            return []
    status, output = apply_reset(database, lst_chosen)
    print(output.strip()[-2000:])
    if status == 2:
        print(f"❌ {t('Reset failed, nothing was changed.')}")
        return []
    return lst_chosen


def run(
    database,
    port,
    config_path,
    limit=None,
    timeout=30,
    boot=180,
    interactive=False,
    auto_apply=False,
    ask=input,
):
    """Démarrer, interroger, arrêter, LIRE, éventuellement corriger, revérifier.

    L'ordre porte tout le correctif : un serveur qui écrit dans un fichier
    bufferise et ne vide qu'en s'arrêtant. Lire avant l'arrêt donnait
    vingt-quatre lignes de démarrage et zéro trace — donc « aucune vue en
    cause » sur des pages qui en nommaient une. Mesuré deux fois avant d'être
    compris.
    """
    import tempfile

    base_url = f"http://127.0.0.1:{port}"
    log_path = os.path.join(
        tempfile.gettempdir(), f"erplibre_smoke_{database}_{port}.log"
    )
    if port_is_taken(port):
        raise RuntimeError(
            f"{t('Something already listens on port')} {port} :"
            f" {t('it would be tested instead of this database.')}"
        )
    server = start_server(database, port, config_path, log_path=log_path)
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
        lst_failure = check_urls(lst_url, timeout=timeout)
    finally:
        stop_server(server)

    if lst_failure:
        lst_failure = attach_missing_parents(lst_failure, read_log(log_path))
    lst_key = culprit_keys(database, lst_failure)
    if not lst_failure or not (interactive or auto_apply):
        return lst_url, lst_failure, lst_key, None

    print(render(lst_url, lst_failure, lst_key))
    if auto_apply:
        lst_done = lst_key
        if lst_done:
            code, output = apply_reset(database, lst_done)
            print(output.strip()[-2000:])
            if code == 2:
                lst_done = []
    else:
        lst_done = prompt(database, lst_failure, lst_key, ask=ask)
    if not lst_done:
        return lst_url, lst_failure, lst_key, None

    server = start_server(database, port, config_path, log_path=log_path)
    try:
        if not wait_ready(base_url, timeout=boot):
            raise RuntimeError(
                f"{t('The server never answered on')} {base_url}"
            )
        lst_again = check_urls(
            [url for url, _s, _p in lst_failure], timeout=timeout
        )
    finally:
        stop_server(server)
    return lst_url, lst_failure, lst_key, lst_again


def stop_server(server):
    """Arrêter tout le GROUPE : sinon odoo-bin survit à son script."""
    try:
        group = os.getpgid(server.pid)
    except OSError:
        group = None
    if group is not None:
        try:
            os.killpg(group, signal.SIGTERM)
        except OSError:
            pass
    try:
        server.wait(timeout=30)
    except subprocess.TimeoutExpired:
        if group is not None:
            try:
                os.killpg(group, signal.SIGKILL)
            except OSError:
                pass
        server.kill()
    handle = getattr(server, "erplibre_log", None)
    if handle:
        handle.close()


def port_is_taken(port, host="127.0.0.1"):
    """Quelqu'un écoute-t-il déjà là ?

    Sans cette question, un serveur resté d'un essai précédent répond à
    « le serveur est-il prêt ? », et l'on teste sa base à lui en croyant
    tester la sienne. C'est exactement ce qui est arrivé ici.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(1)
        return sock.connect_ex((host, port)) == 0


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
        "--apply",
        action="store_true",
        help="reset the views in cause without asking (WRITES)",
    )
    parser.add_argument(
        "--report-only",
        action="store_true",
        help="never ask anything, even in front of a terminal",
    )
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
    interactive = not config.report_only and can_ask()
    try:
        lst_url, lst_failure, lst_key, lst_again = run(
            config.database,
            config.port,
            config.config,
            limit=config.limit,
            timeout=config.timeout,
            boot=config.boot_timeout,
            interactive=interactive,
            auto_apply=config.apply,
        )
    except RuntimeError as exc:
        print(f"❌ {exc}")
        return 2
    if lst_again is None:
        print(render(lst_url, lst_failure, lst_key))
        return 1 if lst_failure else 0
    # Après correction on ne redit pas le diagnostic : on dit ce qu'il RESTE.
    print(
        f"\n↻ {t('Re-checked the')} {len(lst_failure)}"
        f" {t('failing URL(s) after the reset')} :"
    )
    print(render([url for url, _s, _p in lst_failure], lst_again, None))
    return 1 if lst_again else 0


if __name__ == "__main__":
    sys.exit(main())
