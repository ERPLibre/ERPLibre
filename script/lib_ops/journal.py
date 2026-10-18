# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Lire le journal d'Odoo : enregistrements multi-lignes, groupes, bruit.

Un ENREGISTREMENT est une ligne d'en-tête au format d'Odoo suivie de ses
lignes de continuation — une trace Python, la raison PostgreSQL d'une
requête refusée, un message sur plusieurs lignes :

    2026-01-15 03:00:00,123 4242 ERROR base odoo.http: message [perf]

Le format est `%(asctime)s %(pid)s %(levelname)s %(dbname)s %(name)s:
%(message)s`, suivi en 13+ de `%(perf_info)s` (vide hors requête HTTP,
d'où une espace finale, retirée ici). La base vaut `?` hors requête.
L'heure de l'en-tête est en UTC : Odoo pose `TZ=UTC` au démarrage.

Trois formes d'entrée sont lues ligne à ligne, sans les distinguer
d'avance :

- un fichier de journal d'Odoo, ou `journalctl -o cat` : la ligne d'Odoo
  telle quelle ;
- `journalctl -o short-iso` (ou `short-iso-precise`) : chaque ligne
  préfixée de `date hôte identifiant[pid]: `. L'heure de ce préfixe est
  LOCALE et l'emporte sur celle de l'en-tête. Une ligne de systemd lui-même
  (identifiant `systemd` ou `systemd-…`) clôt l'enregistrement en cours :
  « Stopping… » ne se colle pas à la trace qui précède ;
- les lignes de journalctl qui commencent par `-- ` (début de démarrage,
  « No entries », `-- cursor: …` de `--show-cursor`) sont sautées ; le
  dernier curseur est retenu dans `Decoupeur.curseur`.

Toutes les heures rendues sont locales et portent leur décalage. Les
codes de couleur ANSI (`ODOO_PY_COLORS`, sortie vers un terminal) sont
retirés. Une ligne est coupée à `LIGNE_MAX` avant toute expression
régulière.

Limite connue : journald attribue une ligne au processus qui tient le
flux, si bien que les lignes de plusieurs workers peuvent s'entrelacer
quand l'un écrit plus que `PIPE_BUF` d'un coup. Un nouvel en-tête clôt
toujours l'enregistrement précédent, et une ligne de continuation va au
dernier en-tête lu.

`Analyse` range les enregistrements : traces groupées par leur dernière
ligne d'exception, autres erreurs par logger et message normalisés,
requêtes SQL refusées par table et raison, échecs d'envoi de courriel par
classe (`mail_diagnostic`), bruit connu et motifs `ignorer` à part, et le
nombre d'erreurs par heure. Seuls ERROR et CRITICAL sont « à revoir ».
`resume_json` en donne la forme JSON stable, aux clés anglaises jamais
traduites, que rend `log_check.py --json`. `update_module.py` partage le
découpage et le regroupement (`enregistrements`, `analyser`), pas le
JSON.

Ce module ne lit ni n'écrit aucun fichier, ne lance rien et ne traduit
rien. Bibliothèque standard seulement, sans syntaxe postérieure à
Python 3.7.
"""

from __future__ import annotations

import collections
import datetime
import re

from script.lib_ops import mail_diagnostic

# Longueur lue d'une ligne : au-delà, le reste est ignoré. Une ligne de
# plusieurs centaines de kilo-octets (image en base64 dans une trace) ne
# coûte ainsi jamais plus qu'une ligne de cette taille aux expressions.
LIGNE_MAX = 65536

NIVEAUX_REVUS = ("ERROR", "CRITICAL")
# Un échec d'envoi se lit dès WARNING : certaines versions journalisent
# l'échec d'un lot à ce niveau.
NIVEAUX_COURRIEL = ("WARNING", "ERROR", "CRITICAL")

# Lignes d'un échantillon dans le JSON.
ECHANTILLON_JSON = 40
LONGUEUR_CLE = 200
LONGUEUR_AFFICHEE = 200

RE_ANSI = re.compile(r"\x1b\[[0-9;]*m")

# Préfixe de `journalctl -o short-iso[-precise]` : date, fraction, décalage
# (`-0400`, `-04:00` ou `Z` selon la version de systemd), hôte,
# identifiant, pid.
RE_PREFIXE = re.compile(
    r"^(\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d)(\.\d+)?([+-]\d\d:?\d\d|Z)? "
    r"(\S+) ([^\s\[:]+)(?:\[(\d+)\])?: ?(.*)$"
)

# En-tête d'Odoo. Tout jeton de niveau en capitales est admis.
RE_ENTETE = re.compile(
    r"^(\d{4}-\d\d-\d\d) (\d\d:\d\d:\d\d)(?:,(\d+))? (\d+) ([A-Z_]+) "
    r"(\S+) ([^\s:]+): ?(.*)$"
)

DEBUT_TRACE = "Traceback (most recent call last):"
# Lignes à la colonne 0 qui enchaînent deux traces sans être une
# exception.
CHAINAGES = (
    "Traceback ",
    "During handling of the above exception",
    "The above exception was the direct cause",
)
# Une ligne d'exception : un nom (pointé ou non), puis « : » ou rien
# (`KeyboardInterrupt`).
RE_EXCEPTION = re.compile(r"[A-Za-z_][\w.]*(?::|$)")

# Suite sans espace de 60 caractères ou plus : données en base64, jeton.
RE_BLOB = re.compile(r"[A-Za-z0-9+/=_-]{60,}")
RE_UUID = re.compile(
    r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{12}\b"
)
RE_HEX = re.compile(r"\b[0-9a-f]{7,}\b")
RE_CHIFFRES = re.compile(r"\d+")

# Table d'une requête refusée : celle qu'elle modifie d'abord, sinon la
# première du FROM. `UPDATE SET` est la clause d'un `ON CONFLICT`.
RE_TABLE_ECRITE = re.compile(
    r'(?:INSERT\s+INTO|UPDATE|DELETE\s+FROM)\s+(?!SET\b)"?(\w+)', re.I
)
RE_TABLE_LUE = re.compile(r'\bFROM\s+"?(\w+)', re.I)

# Le texte d'Odoo 12 à 18 qui nomme le courriel en échec.
RE_ID_COURRIEL = re.compile(
    r"failed sending mail \(id: (\d+)\)|processing mail with ID (\d+)"
)

RAISON_ABSENTE = "reason missing"


def _date_odoo(jour, heure, millis):
    """L'heure UTC d'un en-tête d'Odoo, en heure locale avec décalage."""
    moment = datetime.datetime.strptime(f"{jour} {heure}", "%Y-%m-%d %H:%M:%S")
    micro = int((millis or "0").ljust(6, "0")[:6])
    moment = moment.replace(microsecond=micro, tzinfo=datetime.timezone.utc)
    return moment.astimezone()


def _date_journal(base, decalage):
    """L'heure du préfixe de journalctl, en heure locale avec décalage.
    Sans décalage, l'heure est déjà locale."""
    if not decalage:
        return datetime.datetime.strptime(
            base, "%Y-%m-%dT%H:%M:%S"
        ).astimezone()
    if decalage == "Z":
        decalage = "+0000"
    decalage = decalage.replace(":", "")
    return datetime.datetime.strptime(
        base + decalage, "%Y-%m-%dT%H:%M:%S%z"
    ).astimezone()


def iso(moment):
    """Une heure en ISO 8601 à la seconde, avec son décalage, ou ""."""
    return moment.isoformat(timespec="seconds") if moment else ""


def abreger(ligne):
    """Une ligne pour l'affichage : chaque suite de 60 caractères sans
    espace devient `[data: N chars]`, puis la ligne est coupée à 200."""
    ligne = RE_BLOB.sub(lambda m: f"[data: {len(m.group(0))} chars]", ligne)
    if len(ligne) > LONGUEUR_AFFICHEE:
        ligne = ligne[: LONGUEUR_AFFICHEE - 1] + "…"
    return ligne


def cle_message(texte):
    """La clé de regroupement d'un message : UUID → `<uuid>`, nombre
    hexadécimal de 7 chiffres ou plus → `…`, nombre → `N`, coupée à 200.
    `MissingError … res.partner(11,)` et `(12,)` partagent ainsi leur
    clé."""
    texte = RE_UUID.sub("<uuid>", texte or "")
    texte = RE_HEX.sub("…", texte)
    texte = RE_CHIFFRES.sub("N", texte)
    return " ".join(texte.split())[:LONGUEUR_CLE]


def titre_trace(lignes):
    """La ligne d'exception finale d'une trace, abrégée, ou None sans
    trace.

    Après le DERNIER `Traceback (most recent call last):`, les cadres
    (`  File …` et leur code) sont indentés ; la première ligne à la
    colonne 0 qui a la forme d'une exception (`nom.pointé: message`, ou
    un nom seul qui n'est pas un bloc de données) est l'exception la plus
    externe d'une chaîne. Ce qui la
    suit (`DETAIL:`, message sur plusieurs lignes, données en base64) est
    la suite de son message, jamais le titre. Sans ligne de cette forme :
    la dernière ligne non vide qui n'est pas un bloc de données.
    """
    debut = None
    for rang, ligne in enumerate(lignes):
        if ligne.startswith(DEBUT_TRACE):
            debut = rang
    if debut is None:
        return None
    suite = lignes[debut + 1 :]
    for ligne in suite:
        if not ligne or ligne[0].isspace() or ligne.startswith(CHAINAGES):
            continue
        if RE_EXCEPTION.match(ligne) and not RE_BLOB.fullmatch(ligne):
            return abreger(ligne.strip())
    for ligne in reversed(suite):
        propre = ligne.strip()
        if propre and not RE_BLOB.fullmatch(propre):
            return abreger(propre)
    return abreger(lignes[0].strip())


class Enregistrement:
    """Un enregistrement du journal : en-tête analysé et toutes ses lignes.

    `quand` : heure locale avec décalage ; `lignes` : l'en-tête (préfixe
    de journalctl et couleurs retirés) puis ses continuations.
    """

    __slots__ = (
        "quand",
        "pid",
        "niveau",
        "base",
        "logger",
        "message",
        "lignes",
        "_titre",
    )

    def __init__(self, quand, pid, niveau, base, logger, message, ligne):
        self.quand = quand
        self.pid = pid
        self.niveau = niveau
        self.base = base
        self.logger = logger
        self.message = message
        self.lignes = [ligne]
        self._titre = False

    @property
    def entete(self):
        return self.lignes[0]

    @property
    def titre(self):
        """La ligne d'exception finale (`titre_trace`), ou None."""
        if self._titre is False:
            self._titre = titre_trace(self.lignes)
        return self._titre

    @property
    def trace(self):
        return self.titre is not None

    def texte(self):
        return "\n".join(self.lignes)


def raison_sql(enregistrement):
    """La raison PostgreSQL d'un `bad query` : la première ligne de
    continuation qui commence par `ERROR:`, sans ce mot ; "" sinon."""
    for ligne in enregistrement.lignes[1:]:
        propre = ligne.strip()
        if propre.startswith("ERROR:"):
            return propre[len("ERROR:") :].strip()
    return ""


def table_sql(message):
    """La table d'une requête refusée : écrite d'abord, sinon lue ; "?"."""
    trouve = RE_TABLE_ECRITE.search(message) or RE_TABLE_LUE.search(message)
    return trouve.group(1) if trouve else "?"


def est_requete_refusee(enregistrement):
    return enregistrement.logger == "odoo.sql_db" and (
        enregistrement.message.startswith("bad query")
    )


class Decoupeur:
    """Découpe des lignes en enregistrements, une ligne à la fois.

    `ajouter(ligne)` rend l'enregistrement que cette ligne CLÔT, ou None ;
    `finir()` rend le dernier. Les lignes qui précèdent le premier
    en-tête sont perdues : leur en-tête est hors de la fenêtre lue.
    `curseur` porte le dernier `-- cursor:` de journalctl.
    """

    def __init__(self):
        self.courant = None
        self.curseur = None
        self.lignes = 0

    def _clore(self):
        fini, self.courant = self.courant, None
        return fini

    def ajouter(self, ligne):
        ligne = ligne[:LIGNE_MAX].rstrip("\r\n")
        self.lignes += 1
        if ligne.startswith("-- "):
            if ligne.startswith("-- cursor: "):
                self.curseur = ligne[len("-- cursor: ") :].strip() or None
            return None
        ligne = RE_ANSI.sub("", ligne)
        quand = None
        prefixe = RE_PREFIXE.match(ligne)
        if prefixe:
            try:
                quand = _date_journal(prefixe.group(1), prefixe.group(3))
            except ValueError:
                # Date impossible : ce n'est pas un préfixe de journalctl,
                # la ligne est lue telle quelle.
                prefixe = None
        if prefixe:
            identifiant = prefixe.group(5)
            if identifiant == "systemd" or identifiant.startswith("systemd-"):
                return self._clore()
            ligne = prefixe.group(7)
        entete = RE_ENTETE.match(ligne)
        if entete and quand is None:
            jour, heure, millis = entete.group(1, 2, 3)
            try:
                quand = _date_odoo(jour, heure, millis)
            except ValueError:
                # Date impossible (30 février) : la ligne n'est pas un
                # en-tête, mais la suite de l'enregistrement en cours.
                entete = None
        if entete:
            fini = self._clore()
            _jour, _heure, _millis, pid, niveau, base, logger, message = (
                entete.groups()
            )
            self.courant = Enregistrement(
                quand,
                int(pid),
                niveau,
                base,
                logger,
                message.rstrip(),
                ligne.rstrip(),
            )
            return fini
        if self.courant is not None:
            self.courant.lignes.append(ligne)
        return None

    def finir(self):
        return self._clore()


def enregistrements(lignes, decoupeur=None):
    """Les enregistrements de `lignes` (itérable de chaînes), au fil de la
    lecture. `decoupeur` : celui à employer, pour en lire ensuite le
    curseur."""
    decoupeur = decoupeur or Decoupeur()
    for ligne in lignes:
        fini = decoupeur.ajouter(ligne)
        if fini is not None:
            yield fini
    fini = decoupeur.finir()
    if fini is not None:
        yield fini


# --- Bruit connu -----------------------------------------------------------
#
# Chaque entrée : (identifiant stable, test sur un enregistrement ERROR ou
# CRITICAL). Un test lit l'en-tête (logger et message) ou le titre de la
# trace, jamais les cadres : un chemin de module dans un cadre ne doit pas
# cacher une erreur sans rapport. La liste reste courte ; `ignorer` ajoute
# les motifs propres à une installation.

RE_CARTE_SOURCE = re.compile(r"\.map should have been generated through debug")
RE_REPRISE = re.compile(
    r"could not serialize access due to concurrent update|deadlock detected"
)
RE_VAPID = re.compile(r"InvalidVapidError")


def _carte_source(rec):
    """Le contrôleur binaire de `web` refuse la carte source (`.map`)
    d'un paquet d'assets d'une version disparue et rend 404 : un
    navigateur aux outils de développement ouverts sur une page antérieure
    à la régénération des assets."""
    return RE_CARTE_SOURCE.search(rec.message) is not None


def _reprise_serialisation(rec):
    """`odoo.sql_db` journalise la requête qu'un conflit de mise à jour
    concurrente ou un interblocage a fait échouer ; la boucle de reprise
    du service HTTP rejoue alors la transaction. Seule la requête est du
    bruit : une trace dont le titre est `SerializationFailure` est
    l'échec final, après les reprises, et reste à revoir."""
    return est_requete_refusee(rec) and bool(
        RE_REPRISE.search(raison_sql(rec))
    )


def _vapid(rec):
    """Un navigateur renouvelle son abonnement aux notifications push avec
    la clé VAPID publique d'avant une régénération ; Odoo la compare à la
    sienne et refuse. Le navigateur se réabonne avec la bonne clé."""
    return bool(
        RE_VAPID.search(rec.message)
        or (rec.titre and RE_VAPID.search(rec.titre))
    )


BRUIT_CONNU = (
    ("sourcemap", _carte_source),
    ("serialization_retry", _reprise_serialisation),
    ("vapid", _vapid),
)


# --- Analyse ---------------------------------------------------------------


class Groupe:
    """Les enregistrements qui partagent une clé : nombre, première et
    dernière heure, logger et base du premier, titre et échantillon du
    premier (lignes abrégées)."""

    __slots__ = (
        "cle",
        "titre",
        "nombre",
        "premier",
        "dernier",
        "logger",
        "base",
        "echantillon",
        "sql",
        "table",
        "raison",
    )

    def __init__(self, cle, titre, rec):
        self.cle = cle
        self.titre = titre
        self.nombre = 0
        self.premier = rec.quand
        self.dernier = rec.quand
        self.logger = rec.logger
        self.base = rec.base
        self.echantillon = [abreger(ligne) for ligne in rec.lignes]
        self.sql = False
        self.table = ""
        self.raison = ""

    def compter(self, rec):
        self.nombre += 1
        if rec.quand < self.premier:
            self.premier = rec.quand
        if rec.quand > self.dernier:
            self.dernier = rec.quand


class GroupeCourriel:
    """Les échecs d'envoi d'une même classe : nombre, heures, ids des
    courriels nommés par le journal."""

    __slots__ = ("classe", "nombre", "premier", "dernier", "ids")

    def __init__(self, classe, rec):
        self.classe = classe
        self.nombre = 0
        self.premier = rec.quand
        self.dernier = rec.quand
        self.ids = set()

    def compter(self, rec):
        self.nombre += 1
        self.premier = min(self.premier, rec.quand)
        self.dernier = max(self.dernier, rec.quand)
        for trouve in RE_ID_COURRIEL.finditer(rec.texte()):
            self.ids.add(int(trouve.group(1) or trouve.group(2)))


def _trier(groupes):
    """Les groupes par nombre décroissant, puis par clé."""
    return sorted(groupes, key=lambda g: (-g.nombre, g.cle))


class Analyse:
    """Le bilan d'une suite d'enregistrements.

    `ignorer` : motifs compilés, cherchés dans l'en-tête et dans le titre
    de la trace, jamais dans les cadres. `builtin` : appliquer aussi
    `BRUIT_CONNU`. `depuis` / `jusqu` : bornes en secondes Unix ; un
    enregistrement hors de la fenêtre n'est pas compté du tout.
    """

    def __init__(self, ignorer=(), builtin=True, depuis=None, jusqu=None):
        self.ignorer = list(ignorer)
        self.builtin = builtin
        self.depuis = depuis
        self.jusqu = jusqu
        self.enregistrements = 0
        self.a_revoir = 0
        self.premier = None
        self.dernier = None
        self.tracebacks = {}
        self.erreurs = {}
        self.sql = {}
        self.courriels = {}
        self.ignores = collections.OrderedDict()
        self.par_heure = collections.Counter()

    def _ignore(self, rec):
        """L'étiquette qui fait ignorer `rec`, ou None : identifiant du
        bruit connu, ou `--ignore MOTIF`."""
        if self.builtin:
            for identifiant, test in BRUIT_CONNU:
                if test(rec):
                    return identifiant
        for motif in self.ignorer:
            if motif.search(rec.entete) or (
                rec.titre and motif.search(rec.titre)
            ):
                return "--ignore " + motif.pattern
        return None

    def _dans_la_fenetre(self, rec):
        moment = rec.quand.timestamp()
        if self.depuis is not None and moment < self.depuis:
            return False
        return self.jusqu is None or moment < self.jusqu

    def ajouter(self, rec):
        if not self._dans_la_fenetre(rec):
            return
        self.enregistrements += 1
        if self.premier is None or rec.quand < self.premier:
            self.premier = rec.quand
        if self.dernier is None or rec.quand > self.dernier:
            self.dernier = rec.quand
        if rec.niveau not in NIVEAUX_COURRIEL:
            return
        etiquette = self._ignore(rec)
        if etiquette:
            if rec.niveau in NIVEAUX_REVUS:
                self.ignores[etiquette] = self.ignores.get(etiquette, 0) + 1
            return
        classe = mail_diagnostic.classer(rec.texte())
        if classe is not None:
            groupe = self.courriels.get(classe.id)
            if groupe is None:
                groupe = self.courriels[classe.id] = GroupeCourriel(
                    classe, rec
                )
            groupe.compter(rec)
        if rec.niveau in NIVEAUX_REVUS:
            self.a_revoir += 1
            jour = rec.quand.strftime("%Y-%m-%d")
            self.par_heure[(jour, rec.quand.hour)] += 1
            self._grouper(rec).compter(rec)

    def _grouper(self, rec):
        """Le groupe d'un enregistrement à revoir, créé au besoin : trace
        par exception finale, requête refusée par table et raison, autre
        erreur par logger et message."""
        if rec.trace:
            cle = cle_message(rec.titre)
            groupe = self.tracebacks.get(cle)
            if groupe is None:
                groupe = self.tracebacks[cle] = Groupe(cle, rec.titre, rec)
                groupe.sql = rec.titre.startswith("psycopg2")
            return groupe
        if est_requete_refusee(rec):
            table = table_sql(rec.message)
            raison = raison_sql(rec)
            cle = f"{table}: {cle_message(raison) or RAISON_ABSENTE}"
            groupe = self.sql.get(cle)
            if groupe is None:
                groupe = self.sql[cle] = Groupe(
                    cle, f"{table}: {raison or RAISON_ABSENTE}", rec
                )
                groupe.table = table
                groupe.raison = raison
            return groupe
        cle = f"{rec.logger}: {cle_message(rec.message)}"
        groupe = self.erreurs.get(cle)
        if groupe is None:
            groupe = self.erreurs[cle] = Groupe(
                cle, abreger(f"{rec.logger}: {rec.message}"), rec
            )
        return groupe

    def groupes_tracebacks(self):
        return _trier(self.tracebacks.values())

    def groupes_erreurs(self):
        return _trier(self.erreurs.values())

    def groupes_sql(self):
        return _trier(self.sql.values())

    def groupes_a_revoir(self):
        """Traces, erreurs et requêtes refusées, ensemble, par nombre."""
        return _trier(
            list(self.tracebacks.values())
            + list(self.erreurs.values())
            + list(self.sql.values())
        )

    def groupes_courriels(self):
        return sorted(
            self.courriels.values(), key=lambda g: (-g.nombre, g.classe.id)
        )


def analyser(recs, ignorer=(), builtin=True, depuis=None, jusqu=None):
    """L'Analyse des enregistrements `recs`."""
    analyse = Analyse(ignorer, builtin, depuis, jusqu)
    for rec in recs:
        analyse.ajouter(rec)
    return analyse


def resume_json(
    analyse, source=None, fenetre=None, etat=None, code=0, version=None
):
    """Le bilan en dict sérialisable, aux clés stables et anglaises.

    `source` : {"kind", "unit", "path"} ; `fenetre` : {"mode", "since",
    "until"} ; `etat` : {"saved", "path", "reason"} ; `version` : version
    majeure d'Odoo, qui choisit le réglage conseillé pour un échec
    d'envoi. Les textes de réglage restent en anglais.
    """

    def commun(groupe):
        return {
            "count": groupe.nombre,
            "first": iso(groupe.premier),
            "last": iso(groupe.dernier),
        }

    tracebacks = []
    for g in analyse.groupes_tracebacks():
        entree = {
            "key": g.cle,
            "headline": g.titre,
            "logger": g.logger,
            "db": g.base,
        }
        entree.update(commun(g))
        entree["sample"] = g.echantillon[:ECHANTILLON_JSON]
        entree["sql"] = g.sql
        tracebacks.append(entree)
    erreurs = []
    for g in analyse.groupes_erreurs():
        entree = {"key": g.cle, "logger": g.logger, "db": g.base}
        entree.update(commun(g))
        entree["sample"] = g.echantillon[:ECHANTILLON_JSON]
        erreurs.append(entree)
    sql = []
    for g in analyse.groupes_sql():
        entree = {"table": g.table, "reason": g.raison or RAISON_ABSENTE}
        entree.update(commun(g))
        sql.append(entree)
    courriels = []
    for g in analyse.groupes_courriels():
        entree = {"class": g.classe.id, "permanent": g.classe.permanent}
        entree.update(commun(g))
        entree["mail_ids"] = sorted(g.ids)
        entree["setting"] = mail_diagnostic.reglage(g.classe.id, version)
        courriels.append(entree)
    par_heure = {}
    for (jour, heure), nombre in sorted(analyse.par_heure.items()):
        par_heure.setdefault(jour, {})[f"{heure:02d}"] = nombre
    return collections.OrderedDict(
        (
            ("version", 1),
            ("source", source or {}),
            ("window", fenetre or {}),
            ("records", analyse.enregistrements),
            ("to_review", analyse.a_revoir),
            ("tracebacks", tracebacks),
            ("errors", erreurs),
            ("sql", sql),
            ("mail", courriels),
            (
                "ignored",
                [
                    {"label": etiquette, "count": nombre}
                    for etiquette, nombre in sorted(
                        analyse.ignores.items(), key=lambda e: (-e[1], e[0])
                    )
                ],
            ),
            ("by_hour", par_heure),
            ("state", etat or {}),
            ("exit_code", code),
        )
    )


# --- Matrice horaire -------------------------------------------------------

BARRE_MAX = 20


def plages_sans(heures):
    """Les plages d'heures (0 à 23) absentes de `heures`, en texte :
    `00 h–02 h, 04 h–18 h` ; une heure seule s'écrit `05 h`."""
    plages = []
    debut = None
    for heure in range(25):
        libre = heure < 24 and heure not in heures
        if libre and debut is None:
            debut = heure
        elif not libre and debut is not None:
            fin = heure - 1
            plages.append(
                f"{debut:02d} h"
                if debut == fin
                else f"{debut:02d} h–{fin:02d} h"
            )
            debut = None
    return ", ".join(plages)


def tableau_horaire(par_heure, jours, titre_heure="h", titre_total="total"):
    """La matrice heure × jour en lignes de texte.

    `par_heure` : {(jour, heure): nombre} ; `jours` : les jours en
    colonnes, dans l'ordre (les 14 derniers seulement). Seules les heures
    qui ont un compte forment une ligne ; chaque ligne finit par son total
    et une barre d'au plus 20 caractères. Les nombres sont bruts, sans
    séparateur de milliers. Rend [] sans aucun compte.
    """
    jours = list(jours)[-14:]
    heures = sorted({h for (j, h), n in par_heure.items() if n and j in jours})
    if not heures:
        return []
    totaux = {h: sum(par_heure.get((j, h), 0) for j in jours) for h in heures}
    plus_grand = max(totaux.values()) or 1
    largeur = max(
        [5] + [len(str(n)) for n in par_heure.values()] + [len(titre_total)]
    )
    lignes = [
        f"{titre_heure:<5} "
        + " ".join(f"{j[5:]:>{largeur}}" for j in jours)
        + f" {titre_total:>{largeur}}"
    ]
    for h in heures:
        cellules = " ".join(
            f"{par_heure.get((j, h), 0) or '.':>{largeur}}" for j in jours
        )
        barre = "█" * max(1, round(totaux[h] * BARRE_MAX / plus_grand))
        lignes.append(f"{h:02d} h  {cellules} {totaux[h]:>{largeur}} {barre}")
    par_jour = " ".join(
        f"{sum(par_heure.get((j, h), 0) for h in heures):>{largeur}}"
        for j in jours
    )
    lignes.append(
        f"{titre_total:<5} {par_jour} {sum(totaux.values()):>{largeur}}"
    )
    return lignes
