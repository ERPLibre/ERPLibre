#!/usr/bin/env python3
# © 2021-2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Réveiller l'instance dès qu'elle écoute, puis disparaître.

Odoo ne charge le registre d'une base qu'à la PREMIÈRE requête qui la
concerne. Sur une base migrée, ce premier chargement prend des dizaines de
secondes — et c'est la personne qui ouvre la page qui les attend. Lancée
en parallèle de `run.sh`, cette sonde prend ce temps à sa place.

Trois règles, et elles tiennent au fait qu'elle tourne À CÔTÉ du serveur
--------------------------------------------------------------------
1. Elle se TAIT. Une seule ligne, au démarrage, pour dire quelle adresse
   elle a choisie — c'est ce qui permet de comprendre après coup un
   réveil qui n'a pas eu lieu. Ensuite plus rien : ni échec, ni trace.
   Un serveur qu'on arrête au bout de dix secondes est un cas ordinaire,
   pas une erreur, et un message d'erreur dans le journal de `run.sh`
   ferait chercher une panne qui n'existe pas.
2. Elle s'arrête à la PREMIÈRE réponse, quelle qu'elle soit. Un 303 vers
   /web/login, un 404, un 500 : tous prouvent que le registre est chargé,
   ce qui est l'objet. Seul le refus de connexion ne compte pas. En mode
   prefork, une requête par worker, toutes en même temps : chaque worker
   charge son propre registre.
3. Elle meurt au bout de deux minutes. Le réveil est un confort ; une
   sonde qui survit à son serveur en est un autre, mauvais.

Où elle trouve le port
----------------------
D'abord la ligne de commande — `-p 8090` l'emporte sur tout le reste,
c'est ce que la personne vient de taper. Puis `config.conf`, que `run.sh`
a déjà résolu et qu'elle reçoit tel quel. Le journal d'exécution ne sert
qu'en dernier recours : Odoo y écrit « HTTP service (werkzeug) running on
127.0.0.1:8069 » une fois qu'il écoute, ce qui arrive parfois APRÈS le
premier essai — mais c'est aussi la seule source exacte quand le port
demandé était déjà pris.

Le mode profond (--deep)
------------------------
Demandé à la main, ou par `update_module.py --warmup-deep` après un
redémarrage ; jamais par `run.sh`. Les trois règles ci-dessus ne valent
que pour le mode par défaut : le mode profond parle (un bilan), et refuse
une option inconnue (code 2).

1. La première réponse est attendue comme dans le mode par défaut. Les
   requêtes partent ensuite par `--repeat` VOIES : chacune a son client,
   donc ses cookies, et ouvre sa propre session par `/web/login?db=BASE`,
   épinglée à la base. Deux requêtes d'une même session ne partent jamais
   en même temps : Odoo 16+ tire le jeton d'un visiteur anonyme de l'IP,
   de l'User-Agent et du sid, et des requêtes simultanées d'un même sid
   feraient un upsert concurrent de la même ligne `website_visitor`,
   journalisé en ERROR.
2. Les pages : /web/login, /, puis au plus `--max-pages` pages de
   `/sitemap.xml` (un index est descendu d'un cran). Le sitemap porte le
   domaine public : seul le chemin de chaque `<loc>` est gardé, et la
   requête part vers la cible.
3. Les paquets d'assets que ces pages citent (`/web/assets/…`, et les
   paquets `/web/content/…assets_…` des versions anciennes). Les corps
   sont lus et jetés.
   Une page ou un paquet est demandé d'abord une fois seul, par la
   première voie — ce premier rendu compile les gabarits ou construit le
   paquet sans concurrence —, puis une fois par chacune des `--repeat` − 1
   autres voies, toutes à la fois, pour atteindre plusieurs workers :
   certains caches sont propres à chacun. Ce qui échoue à la première
   requête n'est pas redemandé.
4. Avec `--login` et `--api-key-file` seulement : `common.login` par
   /jsonrpc, la clé d'API comme mot de passe — Odoo n'accepte une clé que
   hors d'une connexion interactive, donc jamais par
   /web/session/authenticate. Puis, par `execute_kw`, des méthodes de
   lecture seules, d'une liste fermée vérifiée dans le code :
   `res.users.context_get`, `ir.ui.menu.load_menus`, et pour chaque
   modèle de `--models`, `get_views` (16+) ou `load_views` (15 et avant),
   chaque appel une fois par voie, toutes à la fois. Chaque appel porte
   l'uid et la clé : aucune voie n'ouvre de session authentifiée.
   La clé est lue dans un fichier, sans suivre de lien ; elle ne paraît
   ni sur la ligne de commande, ni dans la sortie. Elle ne part qu'en
   https, ou en http vers la boucle locale : une cible http:// sur un
   autre hôte est refusée (code 2).

Le profil de l'instance (`script/lib_ops/profil.py`, groupe `warmup`)
ne vaut que pour le mode profond : `analyser_profond` le lit, la ligne de
commande gagne, et une ligne `🔧 profile:` le dit. Le mode par défaut ne
le lit jamais et n'importe même pas la bibliothèque : `run.sh` ne se
configure pas.

Dans une unité qui reçoit le credential `warmup.api_key`
(`$CREDENTIALS_DIRECTORY/warmup.api_key`, `lib_ops/credentials.py`), ce
fichier est la clé d'API : il passe avant `--api-key-file` et le profil,
et rend effectif le `login` du profil même quand celui-ci ne porte qu'une
référence KeePass. Une ligne `🔑` dit d'où vient la clé ; l'avertissement
sur les droits du fichier est sauté pour un credential, dont systemd tient
le dossier.

Une requête échoue sur une absence de réponse ou un code ≥ 500, et sur
une erreur JSON-RPC ; un code 4xx est compté à part (« non public »).
Codes de sortie : 0, même avec des échecs ; 1 avec `--strict` s'il y en
a ; 2 sur une option invalide. `prechauffer_profond` est l'API en
processus.
"""

from __future__ import annotations

import os
import re
import stat
import sys
import time

# Le checkout de l'outil, jamais le cwd : il nomme le dossier des profils.
RACINE = os.path.normpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")
)
sys.path.append(RACINE)

from script.analyse import lib_analyse  # noqa: E402

try:
    from script.todo.todo_i18n import t
except Exception:  # pragma: no cover - repli si i18n indisponible

    def t(key: str) -> str:
        return key


DELAI_TOTAL = 120.0
DELAI_ENTRE_ESSAIS = 1.0
DELAI_REQUETE = 10.0
PORT_PAR_DEFAUT = 8069
HOTE_PAR_DEFAUT = "127.0.0.1"

# Le mode profond : délai de CHAQUE requête (la première construction d'un
# paquet d'assets prend des dizaines de secondes), pages du sitemap,
# requêtes simultanées par page ou appel, modèles dont les vues sont
# chargées. res.partner est dans `base` de 12 à 18.
DELAI_REQUETE_PROFOND = 120.0
PAGES_MAX = 20
REPETITIONS = 4
REPETITIONS_MAX = 16
MODELES_PAR_DEFAUT = ("res.partner",)
# Corps d'une page gardé pour y chercher les assets ; au-delà, coupé.
CORPS_PAGE_MAX = 4 * 1024 * 1024
BLOC = 64 * 1024
CODE_USAGE = 2
CODE_STRICT = 1

# Le groupe du profil que lit le mode profond.
GROUPE = "warmup"

RE_ASSET = re.compile(
    r"""(?:src|href)=["'](/web/(?:assets|content)/[^"']+)["']"""
)
RE_LOC = re.compile(r"<loc>\s*([^<\s]+)\s*</loc>", re.I)
RE_MODELE = re.compile(r"[a-z0-9_]+(?:\.[a-z0-9_]+)+")
EXTENSIONS_NON_HTML = (
    ".css",
    ".gif",
    ".ico",
    ".jpeg",
    ".jpg",
    ".js",
    ".json",
    ".mp4",
    ".pdf",
    ".png",
    ".svg",
    ".txt",
    ".webp",
    ".woff",
    ".woff2",
    ".xml",
    ".zip",
)
# Les seules méthodes qu'`executer_lecture` appelle, et les modèles où elles
# sont admises (None : tout modèle validé par RE_MODELE).
METHODES_LECTURE = {
    "context_get": ("res.users",),
    "load_menus": ("ir.ui.menu",),
    "get_views": None,
    "load_views": None,
}

# « HTTP service (werkzeug) running on 127.0.0.1:8069 »
MOTIF_JOURNAL = re.compile(
    r"HTTP service \(werkzeug\) running on ([^:\s]+):(\d+)"
)


def port_de_la_ligne(argv):
    """Le port demandé sur la ligne de commande, ou None.

    `-p 8090`, `--http-port 8090` et `--http-port=8090` : les trois
    formes existent, et Odoo les accepte toutes.
    """
    for index, argument in enumerate(argv):
        if argument in ("-p", "--http-port") and index + 1 < len(argv):
            valeur = argv[index + 1]
            if valeur.isdigit():
                return int(valeur)
        if argument.startswith("--http-port="):
            valeur = argument.split("=", 1)[1]
            if valeur.isdigit():
                return int(valeur)
    return None


def adresse_du_journal(chemin, taille=8192):
    """(hôte, port) lus dans la fin du journal, ou (None, None).

    On ne lit que la queue : un journal de migration pèse des mégaoctets,
    et la ligne qu'on cherche est la dernière écrite.
    """
    if not chemin or not os.path.isfile(chemin):
        return None, None
    try:
        with open(chemin, "rb") as handle:
            handle.seek(0, os.SEEK_END)
            debut = max(0, handle.tell() - taille)
            handle.seek(debut)
            queue = handle.read().decode("utf-8", "replace")
    except OSError:
        return None, None
    trouve = MOTIF_JOURNAL.findall(queue)
    if not trouve:
        return None, None
    hote, port = trouve[-1]
    return hote, int(port)


def adresse(argv=(), config_path=None, journal=None):
    """(hôte, port) à réveiller, dans l'ordre de ce qui fait autorité."""
    config = lib_analyse.read_config(config_path)

    port = port_de_la_ligne(argv)
    hote = None
    if port is None:
        hote, port = adresse_du_journal(journal)
    if port is None:
        # xmlrpc_port : l'ancien nom, qu'écrit script/generate_config.sh et
        # qu'Odoo lit encore comme http_port.
        brut = str(
            config.get("http_port") or config.get("xmlrpc_port") or ""
        ).strip()
        port = int(brut) if brut.isdigit() else PORT_PAR_DEFAUT

    if not hote:
        interface = str(config.get("http_interface", "")).strip()
        # Une interface vide veut dire « toutes » : on se parle à soi-même.
        # 0.0.0.0 n'est pas une adresse de destination.
        if interface.lower() in ("", "false", "none", "0.0.0.0", "::"):
            hote = HOTE_PAR_DEFAUT
        else:
            hote = interface
    return hote, port


def nombre_de_workers(argv=(), config_path=None):
    """Le nombre de processus qui servent HTTP, au moins 1.

    En mode prefork, chaque worker charge SON registre à sa première
    requête : réveiller le serveur, c'est réveiller chacun d'eux. `--workers`
    de la ligne de commande d'abord, puis `workers` de la configuration ;
    0, ou absent, est le mode threadé, un seul registre.
    """
    valeur = None
    for index, argument in enumerate(argv):
        if argument == "--workers" and index + 1 < len(argv):
            valeur = argv[index + 1]
        elif argument.startswith("--workers="):
            valeur = argument.split("=", 1)[1]
    if valeur is None:
        valeur = lib_analyse.read_config(config_path).get("workers", "")
    valeur = str(valeur).strip()
    return max(1, int(valeur)) if valeur.isdigit() else 1


def base_a_reveiller(argv=(), config_path=None):
    """La base dont on veut le registre, ou None.

    `-d` d'abord : c'est celle que `run.sh` vient de choisir. Sinon
    `db_name` de la configuration, qu'Odoo utiliserait de toute façon.
    """
    for index, argument in enumerate(argv):
        if argument in ("-d", "--database") and index + 1 < len(argv):
            return argv[index + 1]
        if argument.startswith("--database="):
            return argument.split("=", 1)[1]
    valeur = str(
        lib_analyse.read_config(config_path).get("db_name", "")
    ).strip()
    return valeur if valeur.lower() not in ("", "false", "none") else None


def url(hote, port, database=None):
    """L'adresse à demander.

    `/web/login` plutôt que `/` : elle ne redirige pas vers un tableau de
    bord, ne crée pas de session, et suffit à faire charger le registre.
    Le paramètre `db` dit LAQUELLE quand plusieurs bases répondent.
    """
    base = f"http://{hote}:{port}/web/login"
    if database:
        from urllib.parse import quote

        return f"{base}?db={quote(database)}"
    return base


def ouvrir_sans_proxy(cible, timeout):
    """`urlopen` sans le proxy de l'environnement : `http_proxy` et
    `HTTP_PROXY` sont ignorés, `no_proxy` vide ou non. La cible est
    l'instance elle-même ; passée par un proxy, une réponse du proxy
    (502, 403) se lirait comme celle d'Odoo, et un proxy injoignable
    comme un Odoo muet. Même règle que `Client` et que health_check."""
    import urllib.request

    ouvreur = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    return ouvreur.open(cible, timeout=timeout)


def sonder(
    cible,
    delai_total=DELAI_TOTAL,
    entre_essais=DELAI_ENTRE_ESSAIS,
    requete=DELAI_REQUETE,
    horloge=time.monotonic,
    dormir=time.sleep,
):
    """Demander jusqu'à obtenir une réponse. Rendre True si elle est venue.

    N'importe quel code HTTP est une réussite : 303, 404 ou 500 prouvent
    tous que le serveur a répondu, donc que le registre est chargé. Seul
    le refus de connexion fait recommencer. La requête part directement
    vers la cible, jamais par le proxy de l'environnement
    (`ouvrir_sans_proxy`).
    """
    return bool(
        premier_code(
            cible, delai_total, entre_essais, requete, horloge, dormir
        )
    )


def premier_code(
    cible,
    delai_total=DELAI_TOTAL,
    entre_essais=DELAI_ENTRE_ESSAIS,
    requete=DELAI_REQUETE,
    horloge=time.monotonic,
    dormir=time.sleep,
):
    """Le code HTTP de la première réponse de `cible`, ou 0 si aucune
    n'est venue dans `delai_total` secondes. Les mêmes essais que
    `sonder` : seul le refus de connexion fait recommencer, et une
    réponse 4xx ou 5xx rend son code. Une réponse sans code lisible
    compte pour 200 ; les redirections sont suivies."""
    import urllib.error

    fin = horloge() + delai_total
    while horloge() < fin:
        try:
            with ouvrir_sans_proxy(cible, requete) as reponse:
                return getattr(reponse, "status", None) or 200
        except urllib.error.HTTPError as err:
            # Le serveur a répondu : son code dit comment.
            return err.code or 500
        except Exception:  # noqa: BLE001 - un serveur pas encore prêt
            pass
        dormir(entre_essais)
    return 0


def sonder_tous(cible, workers, delai_total=DELAI_TOTAL, sonde=None):
    """Lance `workers` sondes EN MÊME TEMPS ; rend le nombre de réponses.

    Un worker qui charge son registre n'accepte pas d'autre connexion : la
    deuxième requête simultanée atterrit sur un autre worker, et ainsi de
    suite. Envoyées l'une après l'autre, elles iraient toutes au premier,
    déjà réveillé.
    """
    import threading

    sonde = sonde or sonder
    reponses = []

    def une():
        reponses.append(sonde(cible, delai_total=delai_total))

    fils = [threading.Thread(target=une, daemon=True) for _ in range(workers)]
    for fil in fils:
        fil.start()
    for fil in fils:
        fil.join()
    return sum(1 for ok in reponses if ok)


# --- Le mode profond ------------------------------------------------------


class Bilan:
    """Ce que le préchauffage profond a fait : pages, assets et appels RPC
    comptés une fois chacun (quel que soit `repeat`), `echecs` et
    `non_publics` en (quoi, code ou message), `duree` en secondes,
    `connexion` ("" sans --login, "ok" ou "refused"), `version` d'Odoo lue
    par RPC (None sans --login)."""

    def __init__(self):
        self.pages = 0
        self.assets = 0
        self.rpc = 0
        self.echecs = []
        self.non_publics = []
        self.duree = 0.0
        self.connexion = ""
        self.version = None

    def noter(self, quoi, code):
        """Range l'issue d'une requête : échec sur 0 (pas de réponse) ou
        ≥ 500, « non public » sur 4xx."""
        if code == 0 or code >= 500:
            self.echecs.append((quoi, code))
        elif code >= 400:
            self.non_publics.append((quoi, code))


def _pire(codes):
    """Le code qui résume des requêtes répétées : un échec d'abord, puis
    un refus 4xx, sinon le premier."""
    for code in codes:
        if code == 0 or code >= 500:
            return code
    for code in codes:
        if code >= 400:
            return code
    return codes[0]


class Client:
    """Un ouvreur et sa session — une voie du mode profond : cookies
    gardés (la session reste sur la base choisie par `?db=`), proxy de
    l'environnement ignoré, redirections suivies sur le même hôte
    seulement — une redirection vers un autre hôte est rendue telle quelle
    (3xx). Le certificat d'une cible https est vérifié : la clé d'API y
    passe. Un client ne sert qu'une requête à la fois : des requêtes
    simultanées vont chacune par sa voie."""

    def __init__(self, base_url, delai=DELAI_REQUETE_PROFOND):
        import http.cookiejar
        import urllib.parse
        import urllib.request

        hote = urllib.parse.urlsplit(base_url).hostname

        class MemeHote(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, req, fp, code, msg, headers, newurl):
                if urllib.parse.urlsplit(newurl).hostname != hote:
                    return None
                return super().redirect_request(
                    req, fp, code, msg, headers, newurl
                )

        self.base_url = base_url.rstrip("/")
        self.delai = delai
        self.ouvreur = urllib.request.build_opener(
            urllib.request.ProxyHandler({}),
            urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()),
            MemeHote(),
        )

    def obtenir(self, chemin, garder=False, donnees=None, entetes=None):
        """GET `chemin` (POST avec `donnees`) : (code, corps). Le corps est
        lu par blocs et jeté, ou gardé jusqu'à CORPS_PAGE_MAX si `garder`.
        Code 0 sans réponse ; ne lève pas."""
        import urllib.error
        import urllib.request

        tete = {"User-Agent": "ERPLibre-warmup", "Accept-Encoding": "identity"}
        tete.update(entetes or {})
        requete = urllib.request.Request(
            self.base_url + chemin, data=donnees, headers=tete
        )
        try:
            with self.ouvreur.open(requete, timeout=self.delai) as reponse:
                return reponse.getcode(), _vider(reponse, garder)
        except urllib.error.HTTPError as err:
            try:
                corps = _vider(err, garder)
            except Exception:  # noqa: BLE001 - le corps d'une erreur
                corps = ""
            return err.code, corps
        except Exception:  # noqa: BLE001 - refus, délai, TLS : code 0
            return 0, ""


def _vider(reponse, garder):
    morceaux, taille = [], 0
    while True:
        bloc = reponse.read(BLOC)
        if not bloc:
            break
        if garder and taille < CORPS_PAGE_MAX:
            morceaux.append(bloc)
            taille += len(bloc)
    return b"".join(morceaux).decode("utf-8", "replace") if garder else ""


def sur_les_voies(fonction, voies):
    """`fonction(voie)` pour chaque voie, toutes à la fois, une par fil ;
    rend les résultats dans l'ordre des voies. Une seule voie : un appel
    direct, sans fil."""
    if len(voies) <= 1:
        return [fonction(voie) for voie in voies]
    from concurrent.futures import ThreadPoolExecutor

    with ThreadPoolExecutor(max_workers=len(voies)) as pool:
        futurs = [pool.submit(fonction, voie) for voie in voies]
        return [futur.result() for futur in futurs]


def ouvrir_voies(base_url, delai, premiere, nombre):
    """`nombre` voies de plus, chacune un `Client` qui ouvre sa session par
    `premiere` (`/web/login?db=BASE`), toutes à la fois : (voies, codes
    des ouvertures). Une ouverture sans réponse laisse la voie sans
    session ; Odoo en crée une à sa première requête."""
    voies = [Client(base_url, delai) for _ in range(max(0, nombre))]
    codes = sur_les_voies(lambda voie: voie.obtenir(premiere)[0], voies)
    return voies, codes


def charger(voies, chemin, garder=False):
    """`chemin` demandé d'abord seul par la première voie, puis une fois
    par chacune des autres, toutes à la fois : (codes, corps de la
    première réponse, gardé si `garder`). La première requête fait seule
    le travail partagé (gabarits compilés, paquet d'assets construit) ;
    une première requête sans réponse ou en 5xx n'est pas répétée."""
    code, corps = voies[0].obtenir(chemin, garder)
    codes = [code]
    if len(voies) > 1 and 0 < code < 500:
        reponses = sur_les_voies(lambda voie: voie.obtenir(chemin), voies[1:])
        codes += [c for c, _corps in reponses]
    return codes, corps


def chemin_local(loc):
    """Le chemin et la requête d'une URL du sitemap, sans schéma ni hôte :
    le sitemap porte le domaine public, la requête part vers la cible. Un
    caractère hors ASCII ou une espace est encodé (%XX) ; un encodage déjà
    présent est gardé.

    None pour un `<loc>` qui n'est ni une URL absolue (schéma et hôte) ni
    un chemin commençant par « / » : le chemin rendu est collé derrière
    l'adresse de la cible, et « :9999/x » ou « .autre.example/x » y
    changeraient le port ou l'hôte. « //hote/x » (hôte sans schéma) est
    refusé de même.
    """
    import html
    import urllib.parse

    sur = "/%:@!$&'()*+,;=-._~"
    morceaux = urllib.parse.urlsplit(html.unescape(loc.strip()))
    if morceaux.netloc and not morceaux.scheme:
        return None
    absolue = bool(morceaux.scheme and morceaux.netloc)
    brut = morceaux.path or ("/" if absolue else "")
    if not brut.startswith("/"):
        return None
    chemin = urllib.parse.quote(brut, safe=sur)
    if morceaux.query:
        chemin += "?" + urllib.parse.quote(morceaux.query, safe=sur + "?")
    return chemin


def est_html(chemin):
    import urllib.parse

    fin = os.path.splitext(urllib.parse.urlsplit(chemin).path)[1].lower()
    return fin not in EXTENSIONS_NON_HTML


def pages_du_sitemap(client, maximum):
    """Au plus `maximum` chemins de pages HTML de /sitemap.xml, dans
    l'ordre, sans doublon ; un index de sitemaps est descendu d'un
    cran. Un `<loc>` que `chemin_local` refuse est ignoré."""
    code, corps = client.obtenir("/sitemap.xml", garder=True)
    if code != 200 or not corps:
        return []
    locs = RE_LOC.findall(corps)
    if "<sitemapindex" in corps.lower():
        sous = []
        for loc in locs:
            chemin = chemin_local(loc)
            if chemin is None:
                continue
            code, texte = client.obtenir(chemin, garder=True)
            if code == 200:
                sous.extend(RE_LOC.findall(texte))
        locs = sous
    chemins = []
    for loc in locs:
        chemin = chemin_local(loc)
        if chemin is None:
            continue
        if est_html(chemin) and chemin not in chemins:
            chemins.append(chemin)
        if len(chemins) >= maximum:
            break
    return chemins


def assets_de(corps):
    """Les chemins d'assets qu'une page cite, `&amp;` décodé, sans doublon.
    Sous /web/content, seuls les paquets (`assets_`) : le reste est une
    pièce jointe."""
    import html

    chemins = []
    for brut in RE_ASSET.findall(corps or ""):
        chemin = html.unescape(brut)
        if chemin.startswith("/web/content/") and "assets_" not in chemin:
            continue
        if chemin not in chemins:
            chemins.append(chemin)
    return chemins


def lire_cle(chemin):
    """La clé d'API du fichier `chemin`, sans suivre de lien : (clé,
    ouverte), `ouverte` vrai quand le groupe ou les autres peuvent lire le
    fichier. Lève OSError (illisible, lien) ou ValueError (vide, pas un
    fichier)."""
    fd = os.open(chemin, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        mode = os.fstat(fd).st_mode
        if not stat.S_ISREG(mode):
            raise ValueError("not a regular file")
        donnees = os.read(fd, 4096)
    finally:
        os.close(fd)
    cle = donnees.decode("utf-8", "replace").strip()
    if not cle:
        raise ValueError("empty")
    return cle, bool(mode & 0o077)


def appel_rpc(client, service, methode, args):
    """Un appel /jsonrpc : (résultat, erreur). L'erreur est le seul
    message d'Odoo, tronqué ; jamais les arguments."""
    import json

    corps = json.dumps(
        {
            "jsonrpc": "2.0",
            "method": "call",
            "params": {"service": service, "method": methode, "args": args},
            "id": 1,
        }
    ).encode("utf-8")
    code, texte = client.obtenir(
        "/jsonrpc", True, corps, {"Content-Type": "application/json"}
    )
    if code != 200:
        return None, f"HTTP {code}"
    try:
        reponse = json.loads(texte)
    except ValueError:
        return None, "invalid JSON-RPC answer"
    erreur = reponse.get("error")
    if erreur:
        donnees = erreur.get("data") or {}
        message = donnees.get("message") or erreur.get("message") or "error"
        return None, str(message)[:200]
    return reponse.get("result"), ""


def executer_lecture(client, base, uid, cle, modele, methode, args, kwargs):
    """`execute_kw` d'une méthode de METHODES_LECTURE, sur un modèle
    admis. Lève ValueError pour toute autre : la liste fermée est tenue
    ici, quel que soit l'appelant."""
    permis = METHODES_LECTURE.get(methode, ())
    if permis == () or (permis is not None and modele not in permis):
        raise ValueError(f"not a read-only warm-up call: {modele}.{methode}")
    if RE_MODELE.fullmatch(modele) is None:
        raise ValueError(f"invalid model name: {modele}")
    return appel_rpc(
        client,
        "object",
        "execute_kw",
        [base, uid, cle, modele, methode, args, kwargs],
    )


def vues_a_charger(version):
    """(méthode, types de vue) selon la version : `get_views` dès 16,
    `load_views` avant ; le type liste s'appelle `list` en 18, `tree`
    avant. Une version inconnue est traitée comme la plus récente."""
    recente = version is None or version >= 18
    liste = "list" if recente else "tree"
    methode = "get_views" if version is None or version >= 16 else "load_views"
    vues = [[False, liste], [False, "form"], [False, "search"]]
    return methode, vues + [[False, "kanban"]]


def prechauffer_vues(voies, base, login, cle, modeles, bilan):
    """La partie authentifiée : version et `common.login` par la première
    voie, puis les appels de lecture, chacun une fois par voie, toutes à
    la fois. Un appel `execute_kw` porte l'uid et la clé : les voies
    gardent leur session anonyme, aucune n'en ouvre d'authentifiée. Un
    refus de connexion est un échec ; la clé n'entre dans aucun
    message."""
    client = voies[0]

    def propre(message):
        return str(message).replace(cle, "***")

    resultat, _erreur = appel_rpc(client, "common", "version", [])
    bilan.rpc += 1
    try:
        bilan.version = int((resultat or {})["server_version_info"][0])
    except (KeyError, IndexError, TypeError, ValueError):
        bilan.version = None
    uid, erreur = appel_rpc(client, "common", "login", [base, login, cle])
    bilan.rpc += 1
    if not uid:
        bilan.connexion = "refused"
        bilan.echecs.append(("common.login", propre(erreur or "refused")))
        return
    bilan.connexion = "ok"

    def lecture(modele, methode, args, kwargs):
        reponses = sur_les_voies(
            lambda voie: executer_lecture(
                voie, base, uid, cle, modele, methode, args, kwargs
            ),
            voies,
        )
        bilan.rpc += 1
        erreurs = [e for _r, e in reponses if e]
        if erreurs:
            bilan.echecs.append((f"{modele}.{methode}", propre(erreurs[0])))
        return reponses[0][0]

    contexte = lecture("res.users", "context_get", [], {}) or {}
    lecture("ir.ui.menu", "load_menus", [False], {"context": contexte})
    methode, vues = vues_a_charger(bilan.version)
    for modele in modeles:
        lecture(modele, methode, [vues], {"options": {}, "context": contexte})


def prechauffer_profond(
    base_url,
    base=None,
    max_pages=PAGES_MAX,
    repeat=REPETITIONS,
    login=None,
    cle=None,
    modeles=MODELES_PAR_DEFAUT,
    delai=DELAI_REQUETE_PROFOND,
    horloge=time.monotonic,
):
    """Le préchauffage profond de l'instance servie à `base_url` (sans
    chemin) : rend un Bilan, ne lève pas pour un échec HTTP. La première
    réponse doit déjà être venue (`sonder`). `repeat` voies, chacune sa
    session (voir l'en-tête du module) ; la première ouvre la sienne
    seule, avant toute autre requête."""
    import urllib.parse

    bilan = Bilan()
    debut = horloge()
    client = Client(base_url, delai)
    premiere = "/web/login"
    if base:
        premiere += "?db=" + urllib.parse.quote(base)
    code, corps = client.obtenir(premiere, garder=True)
    corps_pages = [corps]
    chemins = ["/web/login", "/"]
    for chemin in pages_du_sitemap(client, max_pages):
        if chemin not in chemins:
            chemins.append(chemin)
    # Une première ouverture sans réponse ou en 5xx n'est pas répétée par
    # les autres voies : la première voie poursuit seule.
    autres, codes = [], []
    if 0 < code < 500:
        autres, codes = ouvrir_voies(base_url, delai, premiere, repeat - 1)
    bilan.noter(premiere, _pire([code] + codes))
    voies = [client] + autres
    for chemin in chemins:
        codes, texte = charger(voies, chemin, garder=True)
        bilan.pages += 1
        bilan.noter(chemin, _pire(codes))
        corps_pages.append(texte)
    assets = []
    for texte in corps_pages:
        for chemin in assets_de(texte):
            if chemin not in assets:
                assets.append(chemin)
    for chemin in assets:
        codes, _corps = charger(voies, chemin)
        bilan.assets += 1
        bilan.noter(chemin, _pire(codes))
    if login and cle:
        prechauffer_vues(voies, base, login, cle, modeles, bilan)
    bilan.duree = horloge() - debut
    return bilan


def afficher_bilan(bilan, login=None):
    """Le bilan en quelques lignes : les comptes, puis au plus dix
    échecs."""
    if bilan.connexion == "refused":
        print(
            "⚠ [ATTN] "
            + t(
                "Login refused for {login}: check the login and the API key"
                " (Odoo 14+)."
            ).format(login=login),
            flush=True,
        )
    print(
        t(
            "Pages: {pages} · assets: {assets} · RPC calls: {rpc} ·"
            " failures: {failures} · not public: {private} · {seconds} s"
        ).format(
            pages=bilan.pages,
            assets=bilan.assets,
            rpc=bilan.rpc,
            failures=len(bilan.echecs),
            private=len(bilan.non_publics),
            seconds=f"{bilan.duree:.1f}",
        ),
        flush=True,
    )
    for quoi, detail in bilan.echecs[:10]:
        print(f"  ✖ {quoi}: {detail}", flush=True)


def _entier_entre(minimum, maximum):
    def convertir(valeur):
        import argparse

        try:
            nombre = int(valeur)
        except ValueError:
            nombre = minimum - 1
        if not minimum <= nombre <= maximum:
            raise argparse.ArgumentTypeError(
                t(
                    "expected an integer from {minimum} to {maximum}: {value}"
                ).format(minimum=minimum, maximum=maximum, value=valeur)
            )
        return nombre

    return convertir


def _modeles(valeur):
    import argparse

    modeles = [m.strip() for m in valeur.split(",") if m.strip()]
    for modele in modeles:
        if RE_MODELE.fullmatch(modele) is None:
            raise argparse.ArgumentTypeError(
                t("invalid model name: {model}").format(model=modele)
            )
    if not modeles:
        raise argparse.ArgumentTypeError(t("empty model list"))
    return tuple(modeles)


def _refus(message):
    print(f"❌ {message}", file=sys.stderr, flush=True)
    return CODE_USAGE


def _cible_profonde(args, systeme=None):
    """(url de base, base) du mode profond : `--url`, `--local` (l'unité
    systemd, détectée par `systeme` — un health_check.Systeme par défaut —
    comme health_check.py), sinon l'adresse du mode par défaut. Lève
    ValueError (message traduit) sur une cible impossible.

    Sans `--service`, l'unité que la lecture du profil a déjà devinée
    (`args.profil.unite_devinee`) est reprise comme unité nommée : la
    détection ne relance pas `systemctl` pour la deviner une seconde
    fois."""
    from script.odoo import health_check

    if args.url:
        try:
            cible = health_check.normaliser_url(args.url)
        except ValueError as err:
            raise ValueError(
                t("invalid URL ({reason}): {value}").format(
                    reason=t(str(err)), value=args.url
                )
            )
        return cible.url, args.database
    if args.local:
        from script.lib_ops import systemd

        try:
            unite = systemd.nom_unite(args.service) if args.service else None
        except ValueError:
            raise ValueError(
                t("invalid service name: {name}").format(name=args.service)
            )
        devinee = getattr(getattr(args, "profil", None), "unite_devinee", None)
        if unite is None and devinee:
            unite = devinee[0]
        try:
            cible = health_check.detecter_locale(
                unite, systeme or health_check.Systeme()
            )
        except health_check.Refus as err:
            raise ValueError(err.message(t))
        return cible.url, args.database or cible.base
    hote, port = adresse(args.odoo_args, args.config, args.log)
    if ":" in hote:
        hote = f"[{hote}]"
    return f"http://{hote}:{port}", args.database or base_a_reveiller(
        args.odoo_args, args.config
    )


def chiffree_ou_locale(base_url):
    """Vrai quand la clé d'API peut passer vers `base_url` : https, ou
    http vers la boucle locale (127.0.0.0/8, ::1, localhost) — le cas de
    `--local` et de l'adresse par défaut. Vers un autre hôte en http, le
    corps JSON-RPC qui porte la clé circulerait en clair."""
    import ipaddress
    import urllib.parse

    morceaux = urllib.parse.urlsplit(base_url)
    if morceaux.scheme.lower() == "https":
        return True
    hote = (morceaux.hostname or "").lower().rstrip(".")
    if hote == "localhost":
        return True
    try:
        return ipaddress.ip_address(hote).is_loopback
    except ValueError:
        return False


def afficher_profil(application):
    """La ligne `🔧 profile: <chemin> (<n>)`, puis une ligne par valeur
    retenue (`--repeat 2 (profile)`) et un ATTN par clé inconnue ou valeur
    écartée. Rien sans profil actif."""
    if application is None or not application.actif:
        return
    print(
        f"🔧 profile: {application.chemin} ({len(application.valeurs)})",
        flush=True,
    )
    for ligne in application.details(t):
        print(f"   {ligne}", flush=True)
    for ligne in application.avertissements(t):
        print("⚠ [ATTN] " + ligne, flush=True)


def _origine_cle(origine):
    """Le libellé traduit de l'origine du fichier de la clé d'API."""
    if origine == "systemd":
        return t("systemd credential")
    if origine == "profil":
        return t("profile")
    return t("command line")


def principal_profond(args, restes, systeme=None):
    """Le mode profond depuis la ligne de commande, `args` venant
    d'`analyser_profond` (profil posé, `valider` passé) : rend le code de
    sortie (voir l'en-tête). `systeme` sert la détection de `--local`."""
    if restes:
        return _refus(
            t("Unknown option(s) with --deep: {options}").format(
                options=" ".join(restes)
            )
        )
    application = getattr(args, "profil", None)
    afficher_profil(application)
    cle = None
    origine = None
    if args.api_key_file:
        origine = application.origine("api_key_file") if application else "cli"
        print(
            "🔑 "
            + t("API key file: {path} ({origin})").format(
                path=args.api_key_file, origin=_origine_cle(origine)
            ),
            flush=True,
        )
        try:
            cle, ouverte = lire_cle(args.api_key_file)
        except (OSError, ValueError):
            return _refus(
                t("Cannot read the API key from {path}.").format(
                    path=args.api_key_file
                )
            )
        if ouverte and origine != "systemd":
            print(
                "⚠ [ATTN] "
                + t(
                    "{path} is readable by other accounts: chmod 600 it."
                ).format(path=args.api_key_file),
                flush=True,
            )
    try:
        base_url, base = _cible_profonde(args, systeme)
    except ValueError as err:
        return _refus(str(err))
    if args.login and not base:
        return _refus(t("A database is required with --login: give -d."))
    if args.login and not chiffree_ou_locale(base_url):
        return _refus(
            t(
                "--login sends the API key: refused over plain http:// to"
                " another host. Use an https:// URL or --local."
            )
        )
    sonde = base_url + "/web/login"
    if base:
        from urllib.parse import quote

        sonde += "?db=" + quote(base)
    print(f"🔥 warmup --deep: {sonde}", flush=True)
    if not sonder(sonde, delai_total=args.timeout):
        print(
            "✖ "
            + t("No answer within {seconds} s.").format(
                seconds=int(args.timeout)
            ),
            flush=True,
        )
        return CODE_STRICT if args.strict else 0
    bilan = prechauffer_profond(
        base_url,
        base,
        max_pages=args.max_pages,
        repeat=args.repeat,
        login=args.login,
        cle=cle,
        modeles=args.models,
    )
    afficher_bilan(bilan, args.login)
    return CODE_STRICT if args.strict and bilan.echecs else 0


def _avant_double_tiret(argv):
    return argv[: argv.index("--")] if "--" in argv else argv


def construire_parseur():
    """Le parser des deux modes, seul : rien n'est analysé ni lancé.

    `argparse` est importé ici, comme tout ce que le mode par défaut
    n'utilise pas, pour que la sonde de `run.sh` démarre vite.
    `allow_abbrev=False` : sans lui, un argument d'Odoo qui commence comme
    une de nos options (`--lo` pour `--log` et `--login`) serait pris pour
    elle, ou ambigu."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Warm up the HTTP registry.", allow_abbrev=False
    )
    parser.add_argument(
        "-c",
        "--config",
        help=t("Odoo configuration file, as run.sh resolved it."),
    )
    parser.add_argument(
        "-d",
        "--database",
        help=t("Database to warm up; default: the one of the configuration."),
    )
    parser.add_argument(
        "--log",
        help=t(
            "Odoo execution log, read for the listening address as a last"
            " resort."
        ),
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=DELAI_TOTAL,
        help=t("Seconds to wait for the first answer; default: {n}.").format(
            n=int(DELAI_TOTAL)
        ),
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help=t("Without --deep: print nothing."),
    )
    parser.add_argument(
        "--deep",
        action="store_true",
        help=t(
            "Deep warm-up: public pages, sitemap pages, their asset bundles,"
            " then optional read-only views; prints a summary."
        ),
    )
    parser.add_argument(
        "--url",
        help=t("With --deep: base URL to warm up instead of the local one."),
    )
    parser.add_argument(
        "--local",
        action="store_true",
        help=t("With --deep: the instance of the detected systemd unit."),
    )
    parser.add_argument(
        "--service", help=t("With --local: systemd unit to use.")
    )
    parser.add_argument(
        "--max-pages",
        type=_entier_entre(1, 1000),
        default=PAGES_MAX,
        help=t(
            "With --deep: pages taken from the sitemap; default: {n}."
        ).format(n=PAGES_MAX),
    )
    parser.add_argument(
        "--repeat",
        type=_entier_entre(1, REPETITIONS_MAX),
        default=REPETITIONS,
        help=t(
            "With --deep: simultaneous requests per page, asset or call, to"
            " reach several workers; default: {n}."
        ).format(n=REPETITIONS),
    )
    parser.add_argument(
        "--login",
        help=t("With --deep: Odoo login for the read-only view warm-up."),
    )
    parser.add_argument(
        "--api-key-file",
        help=t("File holding the Odoo API key of --login (never on argv)."),
    )
    parser.add_argument(
        "--models",
        type=_modeles,
        default=MODELES_PAR_DEFAUT,
        help=t(
            "With --login: models whose views are loaded, commas; default:"
            " {models}."
        ).format(models=",".join(MODELES_PAR_DEFAUT)),
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help=t("With --deep: exit 1 when a request failed."),
    )
    parser.add_argument(
        "odoo_args",
        nargs="*",
        help=t("Odoo arguments, after --: read for the port and the workers."),
    )
    return parser


def valider(parser, args):
    """Les refus du mode profond sur les valeurs finales, profil posé :
    `parser.error`, donc code 2 (`CODE_USAGE`). Les options inconnues
    (`restes`) se refusent dans `principal_profond`."""
    if bool(args.login) != bool(args.api_key_file):
        parser.error(t("--login and --api-key-file go together."))
    if args.service and not args.local:
        parser.error(t("--service requires --local."))


def analyser_profond(argv=None, lanceur=None):
    """La ligne de commande du mode profond, profil du groupe `warmup`
    appliqué : rend `(args, restes)`, `args.profil` décrivant le profil.

    `parse_known_args` : les options inconnues restent dans `restes`. Le
    credential `warmup.api_key` de l'unité, s'il existe, est posé dans
    `args.api_key_file` avant `valider` (`profil.analyser`). Le
    profil n'est cherché par l'unité devinée qu'avec `--local` et un
    `lanceur` (celui de `main`) ; `--url` et l'adresse du mode par défaut
    ne visent aucune unité. Une erreur d'usage ou de profil sort par
    SystemExit (code 2). La bibliothèque du profil n'est importée qu'ici :
    le mode par défaut ne la charge jamais."""
    from script.lib_ops import profil

    parser = construire_parseur()
    args, restes, _application = profil.analyser(
        parser,
        argv,
        GROUPE,
        t,
        RACINE,
        lanceur=lanceur,
        utilise_service=profil.outil(GROUPE).avec_service,
        connus=True,
    )
    valider(parser, args)
    return args, restes


def _main_profond(liste, systeme):
    """Le mode profond de `main` : son propre code de sortie."""
    from script.lib_ops import systemd

    lanceur = systeme.lanceur if systeme is not None else systemd.lancer
    try:
        args, restes = analyser_profond(liste, lanceur=lanceur)
    except SystemExit as sortie:
        return sortie.code or 0
    try:
        return principal_profond(args, restes, systeme)
    except KeyboardInterrupt:
        print(t("Interrupted."), file=sys.stderr)
        return 130


def main(argv=None, systeme=None):
    """Toujours rendre 0 hors du mode profond : personne ne doit lire ce
    code de retour. `systeme` (health_check.Systeme) ne sert qu'à
    `--deep --local`.

    La sonde tourne en arrière-plan d'un `run.sh` qui, lui, rapporte
    l'état d'Odoo. Un code non nul finirait dans un journal et ferait
    croire à une panne du serveur. Le mode profond (`--deep`, avant tout
    `--`) a ses propres codes et son profil : voir l'en-tête. Le mode par
    défaut ne lit jamais de profil.
    """
    liste = list(sys.argv[1:] if argv is None else argv)
    if "--deep" in _avant_double_tiret(liste):
        return _main_profond(liste, systeme)
    parser = construire_parseur()
    # `parse_known_args` et non `parse_args` : les arguments d'Odoo nous
    # traversent, et l'un d'eux ressemblera un jour à une option qu'on ne
    # connaît pas. Une valeur invalide fait sortir argparse par SystemExit :
    # ce serait rompre la seule promesse qui compte ici — ne jamais gêner.
    try:
        args, restes = parser.parse_known_args(liste)
    except SystemExit:
        return 0
    args.odoo_args = list(args.odoo_args) + list(restes)

    try:
        hote, port = adresse(args.odoo_args, args.config, args.log)
        database = args.database or base_a_reveiller(
            args.odoo_args, args.config
        )
        cible = url(hote, port, database)
        workers = nombre_de_workers(args.odoo_args, args.config)
        if not args.quiet:
            fois = f" ×{workers}" if workers > 1 else ""
            print(f"🔥 warmup: {cible}{fois}", flush=True)
        sonder_tous(cible, workers, delai_total=args.timeout)
    except Exception:  # noqa: BLE001 - le réveil est un confort, pas un dû
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
