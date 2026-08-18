#!/usr/bin/env python3
# © 2021-2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Log in as `test` and open the first page of every Odoo app.

Why this exists
---------------
The public smoke test opens what a visitor can reach. It says nothing about
the BACK OFFICE, which is where a migration does most of its damage: a field
dropped from a model but still named in a form view, a widget renamed between
two versions, a stored compute that no longer resolves. None of it stops the
module loading — it stops the day someone opens the app.

Why the `test` user
-------------------
Neutralizing a database installs `user_test`, which copies the SYSTEM user's
groups onto a `test` / `test` login (see its `post_init_hook`). The module is
uninstalled right after, but the user survives — its uninstall hook only
warns. So a neutralized database, and only a neutralized one, can be browsed
without knowing anyone's real password. The tool checks for that user rather
than trusting a flag: a resumed migration may have skipped neutralization,
and a promise in a progression file is not a login.

What is actually exercised
--------------------------
For each app — a root menu — its first page, meaning the first menu below it
that carries an action, which is what the web client opens on a click. Two
calls per app, both server-side:

- ``get_views`` (12→15: ``load_views``) renders EVERY view arch of the
  action. This is where a migration's damage surfaces, and it surfaces as an
  exception rather than an empty screen.
- ``web_search_read`` (12: ``search_read``) loads the first page of records.
  A view can render on an empty model and still explode on real data.

Exit codes: 0 every app answered, 1 some failed, 2 the tool failed.
"""

import argparse
import ast
import json
import os
import re
import sys
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


DEFAULT_LOGIN = "test"
DEFAULT_PASSWORD = "test"
DEFAULT_RECORD_LIMIT = 20

# Deux façons d'écrire le même champ caché selon la version du gabarit :
# l'ordre des attributs n'est pas garanti, et un seul motif en manquait la
# moitié — la connexion échouait alors sans rien dire d'utile.
RE_CSRF = re.compile(
    r"""name=["']csrf_token["']\s+value=["']([^"']+)["']"""
    r"""|value=["']([^"']+)["']\s+name=["']csrf_token["']"""
)
RE_DB_FIELD = re.compile(r"""name=["']db["']""")


def user_state(database, login=DEFAULT_LOGIN, run_psql=None):
    """« present », « absent » ou « unknown ». La nuance n'est pas cosmétique.

    On INTERROGE plutôt que de croire un drapeau : une migration reprise a
    pu sauter la neutralisation, et `state_1_neutralize_database` dirait
    quand même « fait ».

    Mais `run_psql` rend une liste vide DANS LES DEUX CAS — aucune ligne, ou
    requête refusée. Mesuré ici même : un « id » ambigu passait pour « pas
    d'utilisateur test », et l'outil annonçait tranquillement que la base
    n'avait pas été neutralisée. Un COUNT distingue les deux : il rend
    toujours une ligne quand la requête aboutit.
    """
    if run_psql is None:
        from smoke_public_url import run_psql
    sql = (
        "SELECT count(*) FROM res_users" f" WHERE login = '{login}' AND active"
    )
    try:
        rows = run_psql(database, sql)
    except Exception:
        return "unknown"
    if not rows:
        return "unknown"
    try:
        return "present" if int(rows[0][0]) else "absent"
    except (TypeError, ValueError, IndexError):
        return "unknown"


def user_exists(database, login=DEFAULT_LOGIN, run_psql=None):
    """Raccourci : seul « present » vaut oui."""
    return user_state(database, login, run_psql=run_psql) == "present"


class Session:
    """Un client HTTP qui garde son cookie de session.

    `urllib` sans gestionnaire de cookies renvoie chaque appel comme un
    inconnu : on se connecte, puis on interroge en anonyme sans qu'aucune
    erreur ne le signale — juste des résultats vides.
    """

    def __init__(self, base_url, timeout=60):
        import http.cookiejar

        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.jar = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(self.jar)
        )
        self.uid = None
        # Le nom des méthodes a changé en cours de route (get_views en 16,
        # load_views avant). On retient celui qui a répondu : chercher à
        # chaque appel doublerait le nombre de requêtes.
        self._views_method = None
        self._read_method = None

    def open(self, path, data=None, headers=None):
        url = self.base_url + path
        request = urllib.request.Request(url, data=data, headers=headers or {})
        try:
            with self.opener.open(request, timeout=self.timeout) as answer:
                return answer.getcode(), answer.read().decode(
                    "utf-8", errors="replace"
                )
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read().decode("utf-8", errors="replace")
        except Exception as exc:
            return 0, str(exc)

    def rpc(self, path, params):
        """Un appel JSON-RPC. Rend (résultat, erreur) — jamais une exception.

        Une erreur Odoo arrive avec le statut 200 et un objet `error` dans
        le corps : la traiter comme un succès ferait passer une vue cassée
        pour une vue vide.
        """
        payload = json.dumps(
            {
                "jsonrpc": "2.0",
                "method": "call",
                "params": params,
                "id": 1,
            }
        ).encode("utf-8")
        status, body = self.open(
            path, data=payload, headers={"Content-Type": "application/json"}
        )
        if not status:
            return None, {"name": "transport", "message": body[:200]}
        try:
            answer = json.loads(body)
        except ValueError:
            return None, {
                "name": f"HTTP {status}",
                "message": body.strip()[:200],
            }
        if "error" in answer:
            error = answer["error"] or {}
            data = error.get("data") or {}
            return None, {
                "name": data.get("name") or error.get("message") or "error",
                "message": (
                    data.get("message") or error.get("message") or ""
                ).strip(),
                "debug": data.get("debug") or "",
            }
        return answer.get("result"), None

    def call_kw(self, model, method, args, kwargs=None):
        return self.rpc(
            "/web/dataset/call_kw",
            {
                "model": model,
                "method": method,
                "args": args,
                "kwargs": kwargs or {},
            },
        )

    def log_in(self, database, login, password):
        """Se connecter par le formulaire, comme le ferait un navigateur.

        Le jeton CSRF n'est pas une formalité : sans lui Odoo rend la page
        de connexion avec un statut 200, et l'on croirait être entré.
        """
        status, body = self.open("/web/login")
        if not status:
            return False, t("The server did not serve the login page.")
        match = RE_CSRF.search(body)
        fields = {
            "login": login,
            "password": password,
            "redirect": "",
        }
        if match:
            fields["csrf_token"] = match.group(1) or match.group(2)
        # Le champ `db` n'existe que si le serveur en propose plusieurs.
        # L'envoyer toujours n'est pas anodin : certaines versions le
        # refusent quand la liste des bases est masquée.
        if RE_DB_FIELD.search(body):
            fields["db"] = database
        self.open(
            "/web/login",
            data=urllib.parse.urlencode(fields).encode("utf-8"),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        # On ne LIT pas la redirection pour juger : on demande au serveur
        # qui il croit que nous sommes.
        info, error = self.rpc("/web/session/get_session_info", {})
        if error:
            return False, f"{error['name']} : {error['message']}"[:200]
        uid = (info or {}).get("uid")
        if not uid:
            return False, t("Wrong login or password for user")
        self.uid = uid
        return True, ""

    def views_of(self, model, lst_view, context=None):
        """Faire rendre les arch côté serveur. C'est LE test.

        `get_views` depuis la 16, `load_views` avant, et la 18 n'a plus que
        le premier. On essaie le moderne, on retombe sur l'ancien.
        """
        kwargs = {"views": lst_view, "options": {}, "context": context or {}}
        lst_try = (
            [self._views_method]
            if self._views_method
            else ["get_views", "load_views"]
        )
        last = None
        for method in lst_try:
            result, error = self.call_kw(model, method, [], dict(kwargs))
            if error is None:
                self._views_method = method
                return result, None
            if not _is_missing_method(error):
                return None, error
            last = error
        return None, last

    def first_page(self, model, domain, context, limit, lst_field=None):
        """Charger la première page d'enregistrements.

        `search_read` et non `web_search_read` : ce dernier a changé de
        signature en cours de route — `fields` (une liste) est devenu
        `specification` (un dictionnaire) en 17. Mesuré sur une base 18 :
        seize applications sur vingt-cinq échouaient sur
        « unexpected keyword argument 'fields' », c'est-à-dire sur MON
        appel, pas sur la base. `search_read` n'a pas bougé depuis la 12.

        Une vue peut se rendre sur un modèle vide et exploser sur de
        vraies données : un champ calculé qui ne résout plus ne se voit
        qu'une fois qu'il y a quelque chose à calculer.
        """
        return self.call_kw(
            model,
            "search_read",
            [domain, lst_field or ["display_name"]],
            {"limit": limit, "context": context or {}},
        )

    def known_fields(self, model, context=None):
        """Les champs que le modèle porte VRAIMENT, d'après le serveur."""
        result, error = self.call_kw(
            model, "fields_get", [[], ["type"]], {"context": context or {}}
        )
        if error:
            return None, error
        return sorted(result or {}), None


def arch_fields(views):
    """Les champs que la première page affiche, et RIEN de plus.

    Analyse XML et non expression régulière, pour une raison mesurée : une
    vue formulaire embarque les sous-vues de ses one2many, et un
    `<field name="product_id"/>` qui s'y trouve appartient à la LIGNE de
    facture, pas à la facture. Le motif à plat les ramassait aussi et
    rapportait neuf applications « nommant un champ que le modèle n'a
    plus » — toutes fausses. On ne descend donc jamais dans un `<field>`.

    Lire `display_name` seul ne prouverait presque rien : ce sont les
    colonnes de la liste qui font travailler l'ORM, et c'est là qu'un champ
    calculé cassé par une migration se manifeste.
    """
    import xml.etree.ElementTree as ET

    lst_arch = []

    def descendre(noeud):
        if isinstance(noeud, dict):
            arch = noeud.get("arch")
            if isinstance(arch, str):
                lst_arch.append(arch)
            for valeur in noeud.values():
                descendre(valeur)
        elif isinstance(noeud, list):
            for valeur in noeud:
                descendre(valeur)

    descendre(views)

    lst_name = []

    def parcourir(element):
        for enfant in element:
            if enfant.tag == "field":
                nom = enfant.get("name")
                # Un champ pointé vise un sous-modèle : le demander au
                # modèle principal serait une erreur de NOTRE fait.
                if nom and "." not in nom and nom not in lst_name:
                    lst_name.append(nom)
                # On s'arrête là : ce qui est SOUS un champ appartient au
                # modèle de ce champ, pas au nôtre.
                continue
            parcourir(enfant)

    for arch in lst_arch:
        try:
            racine = ET.fromstring(arch)
        except ET.ParseError:
            # Un arch illisible n'est pas une liste de champs vide : c'est
            # une inconnue. La taire vaut mieux que d'inventer.
            continue
        if racine.tag == "field":
            nom = racine.get("name")
            if nom and "." not in nom and nom not in lst_name:
                lst_name.append(nom)
        else:
            parcourir(racine)
    return lst_name


def model_is_unregistered(error):
    """L'erreur dit-elle « ce modèle n'existe pas dans ce registre » ?

    Odoo rend un 404 nu quand `call_kw` vise un modèle absent du registre :
    « 404 Not Found: The requested URL was not found ». C'est illisible, et
    pourtant c'est la trouvaille la plus nette d'une migration — le module
    est installé dans la base, mais son code n'est plus dans l'addons path
    de la version cible. Mesuré : cinq applications sur vingt-cinq.
    """
    return "notfound" in (error.get("name") or "").lower().replace(".", "")


def _is_missing_method(error):
    """L'erreur dit-elle « cette méthode n'existe pas » ?

    Il faut la distinguer d'une vraie panne : retomber sur l'ancien nom
    après une AccessError masquerait l'AccessError derrière un
    « méthode inconnue » qui n'a rien à voir.
    """
    texte = f"{error.get('name', '')} {error.get('message', '')}".lower()
    return (
        "not exist" in texte
        or "unknown method" in texte
        or "attributeerror" in texte
        or "has no attribute" in texte
    )


def menu_rows(session):
    """Les menus que CET utilisateur voit, dans l'ordre où il les voit.

    Par RPC et non par SQL : `ir.ui.menu` filtre selon les droits et rend
    les noms traduits. Lire la table donnerait des menus inaccessibles et,
    depuis la 16, un nom en jsonb qu'il faudrait décoder à la main.
    """
    return session.call_kw(
        "ir.ui.menu",
        "search_read",
        [[], ["id", "name", "parent_id", "sequence", "action"]],
        {"context": {"lang": "en_US"}},
    )


def apps(lst_menu):
    """(application, menu de sa première page) pour chaque application.

    La première page d'une application est ce que le client web ouvre au
    clic : le premier menu, en descendant, qui porte une action. Une
    application qui n'en a aucune n'est pas une erreur — elle n'a rien à
    ouvrir, et le dire évite de la chercher.
    """
    par_parent = {}
    for menu in lst_menu:
        parent = menu.get("parent_id")
        cle = parent[0] if isinstance(parent, (list, tuple)) else None
        par_parent.setdefault(cle, []).append(menu)
    for lst in par_parent.values():
        lst.sort(key=lambda m: (m.get("sequence") or 0, m.get("id") or 0))

    def descendre(menu, vus):
        if menu["id"] in vus:
            return None
        vus.add(menu["id"])
        if menu.get("action"):
            return menu
        for enfant in par_parent.get(menu["id"], []):
            trouve = descendre(enfant, vus)
            if trouve:
                return trouve
        return None

    resultat = []
    for racine in par_parent.get(None, []):
        resultat.append((racine, descendre(racine, set())))
    return resultat


def actionable(lst_menu):
    """TOUS les menus portant une action, pour le balayage complet."""
    return [menu for menu in lst_menu if menu.get("action")]


def split_action(reference):
    """« ir.actions.act_window,42 » -> (« ir.actions.act_window », 42)."""
    if not reference or "," not in str(reference):
        return None, None
    model, _sep, ident = str(reference).partition(",")
    try:
        return model.strip(), int(ident)
    except ValueError:
        return model.strip(), None


def literal(value, fallback):
    """Un domaine ou un contexte, s'il est LITTÉRAL. Sinon le repli.

    Ils contiennent parfois des expressions Python — `uid`, `context_today`
    — que seul le client sait évaluer. Les évaluer ici serait exécuter du
    code venu de la base ; les refuser tout court retirerait la moitié des
    applications du balayage. On teste donc avec un domaine vide, et on le
    DIT dans le rapport.
    """
    if not value or value in ("[]", "{}"):
        return fallback, False
    try:
        return ast.literal_eval(value), False
    except (ValueError, SyntaxError):
        return fallback, True


def view_pairs(view_mode):
    """« list,form » -> [[False, « list »], [False, « form »]].

    `qweb` est écarté : son rendu demande un enregistrement précis et un
    contexte de rapport, pas une ouverture de menu.
    """
    lst = []
    for mode in (view_mode or "list,form").split(","):
        mode = mode.strip()
        if mode and mode != "qweb":
            lst.append([False, mode])
    return lst or [[False, "form"]]


def check_entry(session, app, menu, limit=DEFAULT_RECORD_LIMIT):
    """Ouvrir une entrée de menu. Rend un dict décrivant ce qui s'est passé."""
    resultat = {
        "app": app["name"],
        "menu": menu["name"],
        "action": menu.get("action"),
        "model": None,
        "kind": None,
        "error": None,
        "stage": None,
        "domain_ignored": False,
        "unknown_fields": [],
        "fields_read": 0,
    }
    model_action, ident = split_action(menu.get("action"))
    resultat["kind"] = model_action
    if model_action != "ir.actions.act_window" or not ident:
        # Une action client n'a pas d'arch à rendre, une action serveur
        # ÉCRIT. Ni l'une ni l'autre ne se teste en ouvrant une page.
        return resultat
    fields = ["res_model", "view_mode", "domain", "context", "limit"]
    lst_action, error = session.call_kw(
        "ir.actions.act_window", "read", [[ident], fields]
    )
    if error:
        resultat["error"] = error
        resultat["stage"] = "action"
        return resultat
    if not lst_action:
        return resultat
    action = lst_action[0]
    model = action.get("res_model")
    resultat["model"] = model
    if not model:
        return resultat
    domain, brut_domaine = literal(action.get("domain"), [])
    context, brut_contexte = literal(action.get("context"), {})
    if not isinstance(domain, list):
        domain, brut_domaine = [], True
    if not isinstance(context, dict):
        context, brut_contexte = {}, True
    resultat["domain_ignored"] = brut_domaine or brut_contexte

    views, error = session.views_of(
        model, view_pairs(action.get("view_mode")), context
    )
    if error:
        resultat["error"] = error
        resultat["stage"] = (
            "registry" if model_is_unregistered(error) else "views"
        )
        return resultat

    # Les champs de la page, et ceux que le modèle porte vraiment. L'écart
    # entre les deux EST le dégât d'une migration : une vue qui nomme un
    # champ disparu. Certaines versions le laissent passer au rendu et
    # n'échouent qu'à la lecture — autant le nommer tout de suite.
    lst_arch = arch_fields(views)
    lst_known, error = session.known_fields(model, context)
    if error:
        resultat["error"] = error
        resultat["stage"] = "fields"
        return resultat
    resultat["unknown_fields"] = [
        name for name in lst_arch if name not in lst_known
    ]
    lst_read = [name for name in lst_arch if name in lst_known]
    resultat["fields_read"] = len(lst_read)

    _rows, error = session.first_page(
        model,
        domain,
        context,
        min(limit, action.get("limit") or limit),
        lst_field=lst_read or ["display_name"],
    )
    if error:
        resultat["error"] = error
        resultat["stage"] = "records"
    return resultat


def crawl(session, limit=DEFAULT_RECORD_LIMIT, every_menu=False):
    """Parcourir les applications. Rend (entrées visitées, échecs)."""
    lst_menu, error = menu_rows(session)
    if error:
        raise RuntimeError(
            f"{t('Could not read the menus')} : {error['name']}"
            f" {error['message']}"[:300]
        )
    if every_menu:
        par_id = {menu["id"]: menu for menu in lst_menu}
        lst_entry = [
            (_root_of(menu, par_id), menu) for menu in actionable(lst_menu)
        ]
    else:
        lst_entry = [
            (app, first) for app, first in apps(lst_menu) if first is not None
        ]
    lst_result = [
        check_entry(session, app, menu, limit=limit) for app, menu in lst_entry
    ]
    return lst_result, [item for item in lst_result if item["error"]]


def _root_of(menu, par_id):
    """Remonter jusqu'à l'application, pour dire d'où vient le menu."""
    vus = set()
    courant = menu
    while True:
        parent = courant.get("parent_id")
        cle = parent[0] if isinstance(parent, (list, tuple)) else None
        if cle is None or cle in vus or cle not in par_id:
            return courant
        vus.add(cle)
        courant = par_id[cle]


def render(lst_result, lst_failure):
    """Le rapport. Ce qui a ouvert, et ce qui a refusé de s'ouvrir."""
    lignes = []
    lignes.append(
        f"\n✨ {t('Apps opened as the test user')} :"
        f" {len(lst_result) - len(lst_failure)}/{len(lst_result)}"
    )
    saute = [
        item
        for item in lst_result
        if not item["error"] and item["kind"] != "ir.actions.act_window"
    ]
    if saute:
        lignes.append(
            f"   {len(saute)} {t('not openable this way (client or server')}"
            f" {t('action): nothing to render.')}"
        )
    approx = [item for item in lst_result if item["domain_ignored"]]
    if approx:
        lignes.append(
            f"   {len(approx)} {t('opened with an empty domain: theirs')}"
            f" {t('needs the browser to evaluate it.')}"
        )
    fantomes = [item for item in lst_result if item.get("unknown_fields")]
    if fantomes:
        lignes.append(
            f"\n⚠️  {t('Views naming a field the model no longer has')} :"
        )
        for item in fantomes:
            lignes.append(
                f"   · {item['app']} [{item['model']}] :"
                f" {', '.join(item['unknown_fields'][:8])}"
            )
    if not lst_failure:
        lignes.append(f"✅ {t('Every app opened its first page.')}")
        return "\n".join(lignes)
    lignes.append(f"\n❌ {t('Apps that failed to open')} :")
    ETAPE = {
        "action": t("reading the action"),
        "views": t("rendering the views"),
        "fields": t("listing the model fields"),
        "records": t("loading the first records"),
        "registry": t("model absent from the running registry"),
    }
    for item in lst_failure:
        error = item["error"]
        lignes.append(
            f"   · {item['app']} → {item['menu']}"
            f"  [{item['model'] or '-'}]"
        )
        lignes.append(
            f"     {ETAPE.get(item['stage'], item['stage'])} :"
            f" {error['name']}"
        )
        if item["stage"] == "registry":
            # Le 404 nu d'Odoo ne dit rien d'utile ; ce qu'il faut savoir,
            # c'est que le code du module manque à CETTE version.
            lignes.append(
                f"     {t('installed in the database, but its module code')}"
                f" {t('is not in this addons path.')}"
            )
        else:
            message = (error.get("message") or "").strip().splitlines()
            if message:
                lignes.append(f"     {message[0][:160]}")
    lignes.append(
        f"\nℹ {t('These are back-office failures: the public smoke test')}"
        f" {t('cannot see them.')}"
    )
    return "\n".join(lignes)


def run(base_url, database, login, password, limit, every_menu=False):
    """Se connecter puis parcourir. Lève RuntimeError si l'on ne peut pas."""
    session = Session(base_url)
    ok, raison = session.log_in(database, login, password)
    if not ok:
        raise RuntimeError(f"{t('Could not log in as')} '{login}' : {raison}")
    return crawl(session, limit=limit, every_menu=every_menu)


def main(argv=None):
    parser = argparse.ArgumentParser(
        description=(
            "Log in as the neutralization test user and open the first page"
            " of every Odoo app, reporting what fails."
        )
    )
    parser.add_argument("-d", "--database", required=True)
    parser.add_argument("-c", "--config", default="./config.conf")
    parser.add_argument("-p", "--port", type=int, default=None)
    parser.add_argument("--login", default=DEFAULT_LOGIN)
    parser.add_argument("--password", default=DEFAULT_PASSWORD)
    parser.add_argument(
        "--limit",
        type=int,
        default=DEFAULT_RECORD_LIMIT,
        help="how many records to load per app",
    )
    parser.add_argument(
        "--all-menus",
        action="store_true",
        help="open every menu with an action, not just each app's first page",
    )
    parser.add_argument(
        "--boot-timeout",
        type=int,
        default=180,
        help="how long to wait for the server to answer",
    )
    config = parser.parse_args(argv)

    from smoke_public_url import (
        DEFAULT_PORT,
        port_is_taken,
        start_server,
        stop_server,
        wait_ready,
    )

    port = config.port or DEFAULT_PORT
    etat = user_state(config.database, config.login)
    if etat == "unknown":
        # Ne PAS dire « pas neutralisée » : on ne le sait pas. Le dire
        # ferait croire que le back-office va bien alors qu'on n'a rien vu.
        print(
            f"❌ {t('Could not tell whether the')} '{config.login}'"
            f" {t('user exists in')} '{config.database}'."
        )
        return 2
    if etat == "absent":
        print(
            f"ℹ️  {t('No')} '{config.login}' {t('user in')}"
            f" '{config.database}' :"
            f" {t('the database was not neutralized, nothing to browse.')}"
        )
        return 0
    if port_is_taken(port):
        print(
            f"❌ {t('Something already listens on port')} {port} :"
            f" {t('it would be tested instead of this database.')}"
        )
        return 2
    base_url = f"http://127.0.0.1:{port}"
    print(
        f"⧖ {t('Starting Odoo on')} '{config.database}'"
        f" ({t('port')} {port})…"
    )
    server = start_server(config.database, port, config.config)
    try:
        if not wait_ready(base_url, timeout=config.boot_timeout):
            print(f"❌ {t('The server never answered on')} {base_url}")
            return 2
        lst_result, lst_failure = run(
            base_url,
            config.database,
            config.login,
            config.password,
            config.limit,
            every_menu=config.all_menus,
        )
    except RuntimeError as exc:
        print(f"❌ {exc}")
        return 2
    finally:
        stop_server(server)
    print(render(lst_result, lst_failure))
    return 1 if lst_failure else 0


if __name__ == "__main__":
    sys.exit(main())
