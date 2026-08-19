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


try:
    from script.todo import auto_ask
except Exception:  # pragma: no cover - repli si le pilote est absent
    auto_ask = None


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

# « Template: website.submenu ». Une QWebException de RENDU ne porte pas le
# bloc [view_id …] : elle nomme le gabarit. Mesuré au palier 17 — une copie
# figée appelait `submenu.clean_url()`, méthode renommée `_clean_url()` dans
# la version, et 34 URL sur 37 rendaient 500 sans que rien ne désigne la vue
# fautive.
RE_TEMPLATE = re.compile(r"^Template:\s*([\w.]+)\s*$", re.M)

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
            # Deux lignes par requête, et elles portent le CHEMIN. Sans
            # elles une trace du journal ne peut être rattachée à rien :
            # on l'attribuait à la dernière requête, qui n'était pas la
            # sienne. Mesuré — /my accusé d'une panne appartenant à une
            # application testée après lui.
            "--log-handler=werkzeug:INFO",
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
        # LES DEUX : le parent ET l'enfant. Mesuré sur /contactus — le
        # parent était identique à sa vue module, et c'est l'ENFANT qui
        # portait l'arch périmée. Ne proposer que le parent envoyait
        # réinitialiser une copie qui allait déjà bien.
        for view_id, parent_id in RE_CONTEXT.findall(line):
            for candidate in (parent_id, view_id):
                if candidate not in known and candidate not in extra:
                    extra.append(candidate)
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


def template_keys(lst_log, database):
    """Les gabarits nommés par une QWebException, s'ils ont une copie COW.

    Nommer une clé sans copie enverrait réinitialiser une vue module — donc
    ne rien faire, en silence. On ne propose que ce qui peut l'être.
    """
    lst_key = []
    for line in lst_log:
        for key in RE_TEMPLATE.findall(line):
            if key not in lst_key:
                lst_key.append(key)
    if not lst_key:
        return []
    quoted = ",".join("'" + k.replace("'", "''") + "'" for k in lst_key)
    rows = run_psql(
        database,
        "SELECT DISTINCT key FROM ir_ui_view"
        f" WHERE website_id IS NOT NULL AND key IN ({quoted});",
    )
    with_copy = {row[0] for row in rows if row and row[0]}
    return [key for key in lst_key if key in with_copy]


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


DEFAULT_ANSWER = "a"


def prompt(database, lst_failure, lst_key, ask=None):
    """Proposer de corriger, puis dire ce qu'il reste. Rend les clés traitées.

    Détecter sans offrir le geste, c'est laisser relever des identifiants
    dans une trace pour les traduire en clés à la main — au moment précis où
    l'on veut juste que la page réponde.
    """
    if not lst_key:
        print(f"ℹ -> {t('No parent view named: nothing to offer.')}")
        return []
    if ask is None:
        # Lancé à part par la migration : sans lecteur temporisé, cette
        # question arrêtait net une exécution automatique.
        ask = (
            auto_ask.make_ask(DEFAULT_ANSWER)
            if auto_ask
            else (lambda prompt="": input(prompt) or DEFAULT_ANSWER)
        )
    print(f"\n✨ {t('Copies to reset onto their module view')} :")
    for index, key in enumerate(lst_key, start=1):
        print(f"   [{index}] {key}")
    print(f"   [a] {t('All of the list above')}")
    answer = (
        ask(
            f"💬 {t('Which one(s) to reset?')}"
            f" ({t('numbers separated by commas, Enter = all, n =')}"
            f" {t('nothing')}) : "
        )
        .strip()
        .lower()
    )
    # « n », et non plus le vide : Entrée vaut « toutes » maintenant, et une
    # sortie sans mot pour dire non serait une sortie sans issue.
    if not answer or answer == "n":
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


def render_internal(internal):
    """Afficher le rapport du back-office. Rend True s'il a échoué.

    Ne rien afficher quand la base n'a pas été neutralisée serait laisser
    croire que le back-office a été testé et qu'il va bien.
    """
    if internal is None:
        return False
    if "skipped" in internal:
        if internal.get("loud"):
            # Un saut ATTENDU se dit à voix basse ; un saut qui trahit une
            # panne doit compter comme un échec, sinon le code de sortie
            # annonce que tout va bien.
            print(
                f"\n⚠️  {t('Back office NOT browsed')} : {internal['skipped']}"
            )
            return True
        print(f"\nℹ️  {t('Back office not browsed')} : {internal['skipped']}")
        return False
    import smoke_internal_ui

    print(smoke_internal_ui.render(internal["results"], internal["failures"]))
    return bool(internal["failures"])


def attach_internal_log(internal_report, log_path):
    """Donner à la passe back-office la trace que sa page ne montrait pas.

    APRÈS l'arrêt du serveur, et pas avant : un serveur qui écrit dans un
    fichier bufferise et ne vide qu'en s'arrêtant. La page d'erreur d'Odoo
    en production, elle, se contente de « 500: Internal Server Error » —
    de quoi constater, pas de quoi réparer.
    """
    if not internal_report or not internal_report.get("failures"):
        return
    try:
        import smoke_internal_ui
    except ImportError:
        return
    smoke_internal_ui.attach_log_reason(
        internal_report["failures"], read_log(log_path)
    )


def internal_phase(
    base_url,
    database,
    enabled=True,
    login="test",
    password="test",
    limit=20,
    every_menu=False,
    lst_portal=None,
    required=False,
):
    """Le back-office, si la base a été neutralisée. Rend None sinon.

    La condition n'est pas un drapeau mais l'utilisateur lui-même : la
    neutralisation pose un compte `test` avec les groupes du
    superutilisateur, et c'est le seul moyen d'entrer sans connaître le mot
    de passe de quelqu'un. Une migration reprise a pu sauter l'étape, et le
    fichier de progression dirait quand même « fait ».

    Un échec ICI ne doit pas emporter le test public : il est mesuré, il
    est rapporté, mais le rapport des URL publiques a sa propre valeur.
    """
    if not enabled:
        return None
    try:
        import smoke_internal_ui
    except ImportError:
        # Se taire ici ferait disparaître la passe ENTIÈRE sans un mot, et
        # l'on croirait le back-office testé. Un outil absent est une
        # panne d'installation, pas une base saine.
        return {"skipped": t("smoke_internal_ui.py is missing"), "loud": True}
    etat = smoke_internal_ui.user_state(database, login, run_psql=run_psql)
    if etat == "absent":
        # `required` dit que la migration a NEUTRALISÉ cette base : le
        # compte devrait donc y être. Mesuré — il survit jusqu'au palier
        # 15 puis disparaît, et la passe s'arrêtait sans bruit exactement
        # là où une migration fait le plus de dégâts.
        if required:
            return {
                "skipped": t(
                    "the test user is gone from a neutralized"
                    " database: the back office was NOT checked"
                ),
                "loud": True,
            }
        return {"skipped": t("no test user: the database was not neutralized")}
    if etat != "present":
        # « je ne sais pas » n'est pas « tout va bien » : le dire autrement
        # ferait passer un back-office jamais ouvert pour un back-office sain.
        return {
            "skipped": t("could not tell whether the test user exists"),
            "loud": True,
        }
    try:
        lst_result, lst_failure = smoke_internal_ui.run(
            base_url,
            database,
            login,
            password,
            limit,
            every_menu=every_menu,
            lst_portal=(
                smoke_internal_ui.DEFAULT_PORTAL_PATHS
                if lst_portal is None
                else lst_portal
            ),
        )
    except RuntimeError as exc:
        return {"skipped": str(exc)}
    return {"results": lst_result, "failures": lst_failure}


def run(
    database,
    port,
    config_path,
    limit=None,
    timeout=30,
    boot=180,
    interactive=False,
    auto_apply=False,
    ask=None,
    internal=True,
    internal_login="test",
    internal_password="test",
    internal_limit=20,
    every_menu=False,
    portal=None,
    internal_required=False,
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
        # ICI, pendant que le serveur tourne : le démarrage d'Odoo est ce
        # qui coûte des minutes, pas les requêtes. Un deuxième outil avec
        # son propre serveur doublerait l'attente pour rien.
        internal_report = internal_phase(
            base_url,
            database,
            enabled=internal,
            login=internal_login,
            password=internal_password,
            limit=internal_limit,
            every_menu=every_menu,
            lst_portal=portal,
            required=internal_required,
        )
    finally:
        stop_server(server)

    attach_internal_log(internal_report, log_path)
    lst_key = []
    if lst_failure:
        lst_log = read_log(log_path)
        lst_failure = attach_missing_parents(lst_failure, lst_log)
        lst_key = culprit_keys(database, lst_failure)
        # Les deux sources : le contexte d'héritage quand il existe, le nom
        # du gabarit quand l'échec vient du rendu.
        for key in template_keys(lst_log, database):
            if key not in lst_key:
                lst_key.append(key)
    if not lst_failure or not (interactive or auto_apply):
        return lst_url, lst_failure, lst_key, None, internal_report

    print(render(lst_url, lst_failure, lst_key))
    if auto_apply:
        lst_done = lst_key
        if lst_done:
            code, output = apply_reset(database, lst_done)
            print(output.strip()[-2000:])
            if code == 2:
                lst_done = []
    else:
        # `ask=None` et non `input` : c'est `prompt` qui sait quel défaut
        # lui appartient, et qui pose alors la question par le lecteur
        # temporisé. Forcer `input` ici court-circuitait le mode auto —
        # mesuré, l'invite attendait indéfiniment une frappe pendant une
        # migration lancée en auto-exécution.
        lst_done = prompt(database, lst_failure, lst_key, ask=ask)
    if not lst_done:
        return lst_url, lst_failure, lst_key, None, internal_report

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
    return lst_url, lst_failure, lst_key, lst_again, internal_report


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
    parser.add_argument(
        "--no-internal",
        action="store_true",
        help="skip the back-office pass done as the neutralization test user",
    )
    parser.add_argument("--login", default="test")
    parser.add_argument("--password", default="test")
    parser.add_argument(
        "--record-limit",
        type=int,
        default=20,
        help="how many records each app loads on its first page",
    )
    parser.add_argument(
        "--all-menus",
        action="store_true",
        help="open every menu with an action, not just each app's first page",
    )
    parser.add_argument(
        "--internal-required",
        action="store_true",
        help="the database WAS neutralized: a missing test user is a failure",
    )
    parser.add_argument(
        "--portal",
        default="/my",
        help="portal paths opened while signed in (comma separated, empty"
        " to skip)",
    )
    config = parser.parse_args(argv)

    print(
        f"⧖ {t('Starting Odoo on')} '{config.database}'"
        f" ({t('port')} {config.port})…"
    )
    interactive = not config.report_only and can_ask()
    try:
        lst_url, lst_failure, lst_key, lst_again, internal = run(
            config.database,
            config.port,
            config.config,
            limit=config.limit,
            timeout=config.timeout,
            boot=config.boot_timeout,
            interactive=interactive,
            auto_apply=config.apply,
            internal=not config.no_internal,
            internal_login=config.login,
            internal_password=config.password,
            internal_limit=config.record_limit,
            every_menu=config.all_menus,
            internal_required=config.internal_required,
            portal=[
                path.strip()
                for path in (config.portal or "").split(",")
                if path.strip()
            ],
        )
    except RuntimeError as exc:
        print(f"❌ {exc}")
        return 2
    internal_failed = render_internal(internal)
    if lst_again is None:
        print(render(lst_url, lst_failure, lst_key))
        return 1 if (lst_failure or internal_failed) else 0
    # Après correction on ne redit pas le diagnostic : on dit ce qu'il RESTE.
    print(
        f"\n↻ {t('Re-checked the')} {len(lst_failure)}"
        f" {t('failing URL(s) after the reset')} :"
    )
    print(render([url for url, _s, _p in lst_failure], lst_again, None))
    return 1 if (lst_again or internal_failed) else 0


if __name__ == "__main__":
    sys.exit(main())
