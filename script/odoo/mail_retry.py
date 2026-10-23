#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Lister les courriels d'Odoo en échec d'envoi, et les remettre en file.

Le déroulé
----------
1. Détection, comme `update_module.py` : l'unité (`--service`, sinon celle
   dont WorkingDirectory est ce checkout, sinon la seule active), son
   compte, son dossier, sa configuration et la base (`--db`, sinon `-d`
   de l'unité, sinon `db_name`).
2. Liste, en LECTURE SEULE : une requête psql sous le compte de l'unité
   (`runuser` quand ce n'est pas le compte courant), avec les paramètres
   de connexion de sa configuration passés par l'environnement et
   `PGOPTIONS` qui force une transaction en lecture seule. Elle rend les
   `mail.mail` à l'état `exception` créés dans les `--days` derniers
   jours (30 par défaut), du plus ancien au plus récent : id, date, sujet
   (dans `mail_message`, dont mail.mail hérite), destinataires,
   `failure_reason`, et `failure_type` quand la colonne existe ; plus
   le compte par état, le paramètre `mail.session.batch.size` et la
   version du module `base`. `create_date` est un horodatage UTC sans
   fuseau : la fenêtre se compare à `now() AT TIME ZONE 'UTC'`, quel que
   soit le fuseau de la session.
3. Affichage : chaque courriel avec ses destinataires MASQUÉS
   (`j***@example.org`, nom affiché réduit à son initiale ; `--details`
   montre tout) et sa cause classée par `lib_ops.mail_diagnostic`,
   passagère ou PERMANENTE. Puis les totaux par sujet, par cause et par
   jour, et deux avertissements : une cause permanente échouera de
   nouveau au renvoi tant que le réglage nommé n'est pas corrigé ; plus de
   10 courriels avec `mail.session.batch.size` absent ou au-dessus de 20
   risquent la limite de messages par connexion du serveur.
4. Sélection : `--resend all | oldest N | ids 1,2,3`, avec `--yes` hors
   terminal ; sur un terminal sans `--resend`, un menu ([a] tous,
   [o] les plus anciens, [i] des ids, [n] aucun — le défaut). `--list`
   n'affiche que la liste.
5. Renvoi par l'ORM, jamais par SQL : `odoo_bin.sh shell` de l'unité,
   lancé sous son compte dans son dossier de travail, reçoit sur son
   entrée un court script qui relit les courriels encore en `exception`,
   appelle `action_retry()` quand la méthode existe, sinon
   `write({'state': 'outgoing'})`, valide la transaction (`odoo shell`
   annule à sa sortie ce qui n'est pas validé) et rend son bilan en JSON
   entre deux sentinelles. L'action planifiée « Mail: Email Queue
   Manager » envoie ensuite la file à son prochain passage.

Codes de sortie : 0 aucun échec, ou tous les courriels choisis remis en
file ; 1 des échecs listés et non renvoyés, ou une partie de la
sélection ignorée (déjà renvoyée, supprimée, ou absente de la liste) ;
2 refusé ou impossible (détection, droits, psql, shell sans réponse) ;
130 interrompu.

Root n'est nécessaire que pour devenir le compte de l'unité : lancé sous
ce compte, le programme n'en demande pas. `--dry-run` montre la sélection
et les commandes exactes sans rien écrire ; sans accès à la base, il
montre les commandes prévues et sort en 0.

Bibliothèque standard seulement, sans syntaxe postérieure à Python 3.7 :
le programme se lance aussi par le python3 d'un serveur de production.
"""

from __future__ import annotations

import argparse
import collections
import datetime
import io
import json
import os
import re
import subprocess
import sys
import types

sys.path.append(
    os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))
)

from script.database import odoo_backup  # noqa: E402
from script.lib_ops import mail_diagnostic, report, service  # noqa: E402

try:
    from script.todo.todo_i18n import t
except Exception:  # pragma: no cover - repli si i18n indisponible

    def t(key: str) -> str:
        return key


RACINE = os.path.normpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")
)

CODE_OK = 0
CODE_RESTE = 1
CODE_REFUS = 2
CODE_INTERROMPU = 130

JOURS_PAR_DEFAUT = 30
JOURS_MAX = 3650
LOT_PAR_DEFAUT = 10
DELAI_SHELL = 300
# Au-delà de ce nombre de courriels, un `mail.session.batch.size` absent
# ou plus grand que `LOT_SUR` fait envoyer tout le lot sur une seule
# connexion SMTP.
SEUIL_LOT = 10
LOT_SUR = 20
TOP = 10

DEBUT_JSON = "MAIL_RETRY_JSON_BEGIN"
FIN_JSON = "MAIL_RETRY_JSON_END"

# Le script donné à `odoo shell` sur son entrée. Seule la liste d'ids,
# entiers validés rendus par repr(), y est insérée. `exists()` écarte un
# courriel supprimé entre la liste et le renvoi ; le filtre sur l'état en
# écarte un déjà renvoyé. `action_retry` n'existe pas dans toutes les
# versions : `write` le remplace, au même effet.
SCRIPT_RENVOI = """
import json
mails = env['mail.mail'].sudo().browse(IDS).exists()
mails = mails.filtered(lambda m: m.state == 'exception')
if hasattr(mails, 'action_retry'):
    mails.action_retry()
    methode = 'action_retry'
else:
    mails.write({'state': 'outgoing'})
    methode = 'write'
env.cr.commit()
requeued = sorted(mails.filtered(lambda m: m.state == 'outgoing').ids)
skipped = sorted(set(IDS) - set(requeued))
print('%s')
print(json.dumps({'requested': IDS, 'requeued': requeued,
                  'skipped': skipped, 'method': methode}))
print('%s')
""" % (DEBUT_JSON, FIN_JSON)


def requete_liste(jours):
    """La requête de lecture, en un seul objet JSON. `jours` est un entier
    validé : c'est la seule valeur insérée. `to_jsonb(m)->>'failure_type'`
    rend NULL quand la colonne n'existe pas dans la version lue, sans
    requête de plus."""
    fenetre = (
        "m.create_date > (now() AT TIME ZONE 'UTC')"
        f" - interval '{int(jours)} days'"
    )
    return (
        "SELECT json_build_object("
        "'version', (SELECT latest_version FROM ir_module_module"
        " WHERE name = 'base'),"
        "'batch_size', (SELECT value FROM ir_config_parameter"
        " WHERE key = 'mail.session.batch.size'),"
        "'counts', (SELECT json_object_agg(c.state, c.n) FROM"
        " (SELECT m.state, count(*) AS n FROM mail_mail m"
        f" WHERE {fenetre} GROUP BY m.state) c),"
        "'failures', (SELECT json_agg(f ORDER BY f.date, f.id) FROM"
        " (SELECT m.id,"
        " floor(extract(epoch FROM m.create_date))::bigint AS date,"
        " left(COALESCE(g.subject, ''), 160) AS subject,"
        " left(COALESCE(NULLIF(m.email_to, ''),"
        " (SELECT string_agg(p.email, ', ')"
        " FROM mail_mail_res_partner_rel r"
        " JOIN res_partner p ON p.id = r.res_partner_id"
        " WHERE r.mail_mail_id = m.id), ''), 300) AS recipients,"
        " left(COALESCE(m.failure_reason, ''), 1000) AS reason,"
        " to_jsonb(m)->>'failure_type' AS failure_type"
        " FROM mail_mail m"
        " LEFT JOIN mail_message g ON g.id = m.mail_message_id"
        f" WHERE m.state = 'exception' AND {fenetre}) f))"
    )


# --- Masquage --------------------------------------------------------------

RE_ADRESSE = re.compile(r"([^<>@\s,;\"']+)@([^<>\s,;\"']+)")
RE_NOM_ADRESSE = re.compile(r"^(.*?)<([^<>]*)>\s*$")


def _masquer_adresse(adresse):
    trouve = RE_ADRESSE.search(adresse)
    if not trouve:
        adresse = adresse.strip()
        return adresse[:1] + "***" if adresse else ""
    return f"{trouve.group(1)[:1]}***@{trouve.group(2)}"


def masquer(destinataires):
    """Les destinataires, chaque adresse réduite à son initiale et à son
    domaine (`j***@example.org`), un nom affiché à son initiale
    (`J*** <j***@example.org>`). Séparateurs `,` et `;`."""
    parties = []
    for partie in re.split(r"[,;]", destinataires or ""):
        partie = partie.strip()
        if not partie:
            continue
        nomme = RE_NOM_ADRESSE.match(partie)
        if nomme:
            nom = nomme.group(1).strip().strip("\"'").strip()
            adresse = _masquer_adresse(nomme.group(2))
            parties.append(
                f"{nom[:1]}*** <{adresse}>" if nom else f"<{adresse}>"
            )
        else:
            parties.append(_masquer_adresse(partie))
    return ", ".join(parties)


def masquer_texte(texte):
    """`texte` où chaque adresse est réduite à son initiale et à son
    domaine (`j***@example.org`), le reste intact. La raison d'un échec
    peut nommer les destinataires (`SMTPRecipientsRefused: {'adresse':
    (552, …)}`, rejet 5.1.1) : sa cause passe par ici quand les
    destinataires sont masqués."""
    return RE_ADRESSE.sub(lambda m: _masquer_adresse(m.group(0)), texte or "")


# --- Données ---------------------------------------------------------------


class Echec:
    """Un courriel en échec : id, date (secondes Unix), sujet,
    destinataires, raison, type d'échec, classe et cause courte."""

    def __init__(self, donnees):
        self.id = int(donnees.get("id"))
        self.date = int(donnees.get("date") or 0)
        self.sujet = donnees.get("subject") or ""
        self.destinataires = donnees.get("recipients") or ""
        self.raison = donnees.get("reason") or ""
        self.type = donnees.get("failure_type") or None
        self.classe = mail_diagnostic.classer_echec(self.raison, self.type)
        self.cause = mail_diagnostic.cause_courte(self.raison)

    def jour(self):
        return datetime.datetime.fromtimestamp(self.date).strftime("%Y-%m-%d")

    def heure(self):
        return datetime.datetime.fromtimestamp(self.date).strftime(
            "%Y-%m-%d %H:%M"
        )


def cause_montree(echec, details):
    """La cause courte telle qu'elle sort, au texte comme en JSON :
    entière avec `details`, adresses masquées sinon."""
    return echec.cause if details else masquer_texte(echec.cause)


def libelle_cause(echec, details=False):
    """La cause affichée : le libellé de la classe, sinon la cause
    courte (`cause_montree`), sinon « cause inconnue »."""
    if echec.classe is not None:
        return t(echec.classe.libelle)
    return cause_montree(echec, details) or t("unknown cause")


class Systeme(odoo_backup.Systeme):
    """Les effets de bord : systemctl, psql (`requete`), le shell d'Odoo,
    le terminal. Un test en dérive une classe et rien de réel n'est
    lancé."""

    def __init__(self, verbeux=False, interactif=None, demander=None):
        super().__init__(verbeux=verbeux)
        self.interactif = (
            sys.stdin.isatty() and sys.stdout.isatty()
            if interactif is None
            else interactif
        )
        self.demander = demander or input

    def shell_odoo(self, argv, cwd, source, delai):
        """Lance `argv` dans `cwd`, `source` sur son entrée : (code,
        stdout, stderr). Délai dépassé : 124 ; binaire absent : 127.

        Le processus a sa propre session. `runuser`, puis `env` et
        `bash ./odoo_bin.sh`, s'intercalent entre ce programme et le
        python d'Odoo : tuer le seul enfant direct laisserait ce python
        tourner, valider la remise en file après le constat d'échec et
        garder ses verrous sur `mail_mail`. Au délai dépassé, comme sur
        Ctrl-C ou toute exception, le GROUPE entier est arrêté (TERM, puis
        KILL) et attendu (`odoo_backup._terminer`)."""
        self._tracer(argv)
        try:
            proc = subprocess.Popen(
                argv,
                cwd=cwd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                universal_newlines=True,
                start_new_session=True,
            )
        except OSError as err:
            return 127, "", str(err)
        try:
            sortie, erreurs = proc.communicate(source, timeout=delai)
        except subprocess.TimeoutExpired:
            odoo_backup._terminer(proc)
            _fermer(proc)
            return 124, "", "timeout"
        except BaseException:
            odoo_backup._terminer(proc)
            _fermer(proc)
            raise
        return proc.returncode, sortie or "", erreurs or ""

    def existe(self, chemin):
        return os.path.isfile(chemin)


def _fermer(proc):
    """Ferme les tubes d'un processus arrêté sans les lire : un
    descendant sorti du groupe qui les tiendrait encore ouverts ne bloque
    pas ce programme."""
    for tube in (proc.stdin, proc.stdout, proc.stderr):
        if tube is not None:
            try:
                tube.close()
            except OSError:
                pass


def commande_shell(plan):
    """La commande du shell d'Odoo de l'unité, sous son compte."""
    return service.envelopper(
        [
            "bash",
            "./odoo_bin.sh",
            "shell",
            "-c",
            plan.config_path,
            "-d",
            plan.base,
            "--no-http",
        ],
        plan,
        {"ODOO_RC": plan.config_path},
    )


def script_renvoi(ids):
    """Le script du shell pour ces ids (entiers)."""
    ids = [int(i) for i in ids]
    return "IDS = " + repr(ids) + "\n" + SCRIPT_RENVOI


def lire_bilan(sortie):
    """Le JSON entre les sentinelles de la sortie du shell, ou None."""
    if DEBUT_JSON not in sortie or FIN_JSON not in sortie:
        return None
    morceau = sortie.split(DEBUT_JSON, 1)[1].split(FIN_JSON, 1)[0]
    try:
        donnees = json.loads(morceau.strip())
    except ValueError:
        return None
    return donnees if isinstance(donnees, dict) else None


# --- Affichage -------------------------------------------------------------


def afficher_liste(rapport, args, echecs, donnees, version):
    comptes = donnees.get("counts") or {}
    if comptes:
        rapport.champ(
            t("Mail states"),
            ", ".join(f"{etat}: {n}" for etat, n in sorted(comptes.items())),
        )
    if not echecs:
        rapport.ok(
            t("No failed mail in the last {days} day(s).").format(
                days=args.days
            )
        )
        return
    rapport.texte("")
    rapport.texte(
        t("{count} failed mail(s) in the last {days} day(s):").format(
            count=len(echecs), days=args.days
        )
    )
    for echec in echecs:
        rapport.texte(f"  #{echec.id}  {echec.heure()}  « {echec.sujet} »")
        destinataires = (
            echec.destinataires
            if args.details
            else masquer(echec.destinataires)
        ) or t("(no recipient recorded)")
        ligne = "      {} {} — {} {}".format(
            t("To:"),
            destinataires,
            t("cause:"),
            libelle_cause(echec, args.details),
        )
        if echec.classe is not None:
            ligne += " — " + (
                t("PERMANENT") if echec.classe.permanent else t("transient")
            )
        rapport.texte(ligne)
        if args.details and echec.cause:
            rapport.texte(f"      {echec.cause}")
    for titre, cles in (
        (t("By subject"), [e.sujet or "-" for e in echecs]),
        (t("By cause"), [libelle_cause(e, args.details) for e in echecs]),
        (t("By day"), [e.jour() for e in echecs]),
    ):
        compte = collections.Counter(cles)
        rapport.texte("")
        rapport.texte(titre)
        for cle, n in sorted(compte.items(), key=lambda e: (-e[1], e[0]))[
            :TOP
        ]:
            rapport.texte(f"  {n:>5}  {cle}")
    rapport.texte("")
    permanents = [e for e in echecs if e.classe and e.classe.permanent]
    if permanents:
        rapport.attn(
            t(
                "{count} mail(s) failed for a PERMANENT cause: a resend fails"
                " again until the setting is fixed."
            ).format(count=len(permanents))
        )
        for identifiant in sorted({e.classe.id for e in permanents}):
            classe = mail_diagnostic.PAR_ID[identifiant]
            rapport.detail(
                "{} : {}".format(
                    t(classe.libelle),
                    t(mail_diagnostic.reglage(identifiant, version)),
                )
            )
    lot = donnees.get("batch_size")
    if len(echecs) > SEUIL_LOT and not _lot_sur(lot):
        rapport.attn(
            t(
                "{count} mails and mail.session.batch.size is {value}: a"
                " server limit of messages per connection may refuse part"
                " of the resend; set it to 10 or 20 first."
            ).format(count=len(echecs), value=lot if lot else t("unset"))
        )


def _lot_sur(valeur):
    try:
        return 0 < int(str(valeur).strip()) <= LOT_SUR
    except (TypeError, ValueError):
        return False


# --- Sélection -------------------------------------------------------------


def lire_selection(valeurs):
    """`--resend` en (mode, valeur) : ("all", None), ("oldest", N) ou
    ("ids", [entiers]). Lève ValueError."""
    if not valeurs:
        raise ValueError("")
    mode, reste = valeurs[0].lower(), valeurs[1:]
    if mode == "all" and not reste:
        return "all", None
    if mode == "oldest" and len(reste) == 1:
        nombre = int(reste[0])
        if nombre < 1:
            raise ValueError(reste[0])
        return "oldest", nombre
    if mode == "ids" and reste:
        ids = []
        for morceau in re.split(r"[,\s]+", " ".join(reste)):
            if morceau:
                ids.append(int(morceau))
        if not ids or any(i < 1 for i in ids):
            raise ValueError(" ".join(reste))
        return "ids", ids
    raise ValueError(" ".join(valeurs))


def choisir(echecs, mode, valeur):
    """(ids choisis, ids demandés absents de la liste), dans l'ordre de la
    liste (du plus ancien au plus récent)."""
    listes = [e.id for e in echecs]
    if mode == "all":
        return listes, []
    if mode == "oldest":
        return listes[:valeur], []
    voulus = list(dict.fromkeys(valeur))
    return [i for i in listes if i in voulus], [
        i for i in voulus if i not in listes
    ]


def menu(systeme, echecs):
    """Le choix au terminal : (mode, valeur), ou None pour aucun. Entrée
    vide, réponse inconnue, fin de l'entrée et Ctrl-C valent « aucun »."""
    try:
        reponse = (
            systeme.demander(
                t(
                    "Resend: [a]ll ({count})  [o]ldest batch  [i]ds  [n]one"
                    " [n]: "
                ).format(count=len(echecs))
            )
            .strip()
            .lower()
        )
        if reponse in ("a", "all", "t", "tous"):
            return "all", None
        if reponse in ("o", "oldest"):
            texte = systeme.demander(
                t("How many of the oldest? [{count}]: ").format(
                    count=LOT_PAR_DEFAUT
                )
            ).strip()
            return lire_selection(["oldest", texte or str(LOT_PAR_DEFAUT)])
        if reponse in ("i", "ids"):
            texte = systeme.demander(t("Mail ids (comma list): ")).strip()
            return lire_selection(["ids", texte])
    except (EOFError, KeyboardInterrupt, ValueError):
        return None
    return None


# --- Renvoi ----------------------------------------------------------------


def renvoyer(plan, systeme, rapport, args, ids):
    """Le shell d'Odoo remet `ids` en file : (code, bilan ou None)."""
    argv = commande_shell(plan)
    code, sortie, erreurs = systeme.shell_odoo(
        argv, plan.wd, script_renvoi(ids), args.timeout
    )
    if code == 124:
        rapport.fail(
            t(
                "The Odoo shell exceeded {seconds} s and was stopped: whether"
                " the mails were requeued is unknown; list them again."
            ).format(seconds=args.timeout)
        )
        return CODE_REFUS, None
    bilan = lire_bilan(sortie)
    if bilan is None:
        rapport.fail(
            t("The Odoo shell returned no result (code {code}).").format(
                code=code
            )
        )
        rapport.extrait((erreurs or sortie).strip().splitlines()[-5:], 5)
        return CODE_REFUS, None
    remis = [int(i) for i in bilan.get("requeued") or []]
    ignores = [int(i) for i in bilan.get("skipped") or []]
    if remis:
        rapport.ok(
            t("{count} mail(s) requeued ({ids}).").format(
                count=len(remis), ids=", ".join(f"#{i}" for i in remis)
            )
        )
    if ignores:
        rapport.attn(
            t(
                "{count} mail(s) skipped: no longer failed or deleted ({ids})."
            ).format(
                count=len(ignores), ids=", ".join(f"#{i}" for i in ignores)
            )
        )
    if remis:
        rapport.texte(
            "  "
            + t(
                "The scheduled action 'Mail: Email Queue Manager' sends them"
                " at its next run."
            )
        )
    return (CODE_RESTE if ignores else CODE_OK), bilan


def simuler(plan, rapport, ids):
    rapport.sim(
        t("Would resend {count} mail(s): {ids}").format(
            count=len(ids), ids=", ".join(f"#{i}" for i in ids)
        )
    )
    rapport.sim(
        f"cd {service.joindre([plan.wd])} && "
        + service.joindre(commande_shell(plan))
        + " <<'EOF'"
    )
    for ligne in script_renvoi(ids).strip("\n").splitlines():
        rapport.texte(f"      {ligne}")
    rapport.texte("      EOF")


# --- Programme -------------------------------------------------------------

TYPES = service.types_argparse(t)


def _type_jours(valeur):
    try:
        nombre = int(valeur)
    except ValueError:
        nombre = 0
    if not 1 <= nombre <= JOURS_MAX:
        raise argparse.ArgumentTypeError(
            t("expected a number of days from 1 to {maximum}: {value}").format(
                maximum=JOURS_MAX, value=valeur
            )
        )
    return nombre


def analyser(argv=None):
    parser = argparse.ArgumentParser(
        description=t(
            "List the failed outgoing mails of an Odoo instance (read-only),"
            " then requeue the chosen ones through the Odoo shell."
        )
    )
    parser.add_argument(
        "--service",
        type=TYPES.unite,
        help=t(
            "systemd unit; default: the unit whose WorkingDirectory is this"
            " checkout, else the only active one."
        ),
    )
    parser.add_argument(
        "--db",
        type=TYPES.base,
        help=t("Database; default: -d of the unit, else db_name."),
    )
    parser.add_argument(
        "--odoo-conf",
        help=t("Odoo configuration file; default: the one the unit reads."),
    )
    parser.add_argument(
        "--user",
        type=TYPES.utilisateur,
        help=t("Account of the instance; default: User= of the unit."),
    )
    parser.add_argument(
        "--days",
        type=_type_jours,
        default=JOURS_PAR_DEFAUT,
        help=t("Failed mails of the last DAYS days; default: {days}.").format(
            days=JOURS_PAR_DEFAUT
        ),
    )
    parser.add_argument(
        "--details",
        action="store_true",
        help=t("Show full recipient addresses and failure reasons."),
    )
    parser.add_argument(
        "--resend",
        nargs="+",
        metavar="MODE",
        help=t(
            "Mails to requeue: all, the N oldest, or ids (comma list);"
            " requires --yes without a terminal."
        ),
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help=t("Confirm --resend without asking."),
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help=t("List only: no question, no resend."),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help=t("Show the selection and the exact commands; write nothing."),
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help=t("Print the result as JSON (untranslated keys)."),
    )
    parser.add_argument(
        "--timeout",
        type=TYPES.secondes,
        default=DELAI_SHELL,
        help=t(
            "Maximum seconds for the Odoo shell; default: {seconds}."
        ).format(seconds=DELAI_SHELL),
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help=t("Show each system command on stderr."),
    )
    args = parser.parse_args(argv)
    args.selection = None
    if args.resend:
        try:
            args.selection = lire_selection(args.resend)
        except ValueError:
            parser.error(
                t("invalid --resend: {value}").format(
                    value=" ".join(args.resend)
                )
            )
    if args.list and args.resend:
        parser.error(t("--list cannot be combined with --resend."))
    return args


def resume_json(args, plan, echecs, donnees, renvoi, code):
    return collections.OrderedDict(
        (
            ("database", plan.base),
            ("days", args.days),
            (
                "failures",
                [
                    collections.OrderedDict(
                        (
                            ("id", e.id),
                            (
                                "date",
                                datetime.datetime.fromtimestamp(e.date)
                                .astimezone()
                                .isoformat(timespec="seconds"),
                            ),
                            ("subject", e.sujet),
                            (
                                "recipients",
                                e.destinataires
                                if args.details
                                else masquer(e.destinataires),
                            ),
                            ("cause", cause_montree(e, args.details)),
                            ("class", e.classe.id if e.classe else None),
                            (
                                "permanent",
                                e.classe.permanent if e.classe else None,
                            ),
                        )
                    )
                    for e in echecs
                ],
            ),
            ("counts", donnees.get("counts") or {}),
            ("batch_size", donnees.get("batch_size")),
            ("resend", renvoi),
            ("exit_code", code),
        )
    )


def _simuler_sans_acces(plan, cible, rapport, sql):
    """Ce que ferait un compte qui peut lire la base : la requête psql
    (mot de passe masqué) et la commande du shell."""
    rapport.attn(
        t(
            "Reading the database requires sudo or the account {user}:"
            " planned commands only."
        ).format(user=plan.utilisateur)
    )
    argv = odoo_backup.argv_psql(cible, plan.base, sql)
    rapport.sim(
        odoo_backup.decrire(argv, odoo_backup.variables_pg(cible, True))
    )
    rapport.sim(
        f"cd {service.joindre([plan.wd])} && "
        + service.joindre(commande_shell(plan))
        + " <<'EOF' … EOF"
    )


def lister(args, systeme, rapport):
    """Détection et liste : (code, état). `état` porte `plan`, `echecs`,
    `donnees`, `renvoi` ; il vaut None quand rien n'a pu être lu."""
    plan = types.SimpleNamespace()
    try:
        config = service.detecter_instance(args, systeme, RACINE, plan)
    except service.Refus as err:
        rapport.erreur(err.message(t))
        return CODE_REFUS, None
    cible = odoo_backup.preparer_cible(plan, config, None, None, systeme)
    rapport.champ(t("Service"), plan.unite)
    rapport.champ(t("Account"), plan.utilisateur)
    rapport.champ(t("Database"), f"{plan.base} ({plan.origine_base})")
    sql = requete_liste(args.days)
    odoo_bin = os.path.join(plan.wd, "odoo_bin.sh")
    if args.selection and not systeme.existe(odoo_bin):
        rapport.erreur(
            t("{path} is missing: the Odoo shell cannot be run.").format(
                path=odoo_bin
            )
        )
        return CODE_REFUS, None
    if not cible.interrogeable:
        if args.dry_run:
            _simuler_sans_acces(plan, cible, rapport, sql)
            return CODE_OK, None
        rapport.erreur(
            t(
                "Run as root (sudo) or as {user}; other accounts only with"
                " --dry-run."
            ).format(user=plan.utilisateur)
        )
        return CODE_REFUS, None
    try:
        donnees = odoo_backup.interroger(cible, systeme, plan.base, sql)
    except odoo_backup.ErreurPg as err:
        rapport.erreur(
            t("Cannot read the failed mails of {database}: {error}").format(
                database=plan.base, error=err
            )
        )
        return CODE_REFUS, None
    echecs = [Echec(d) for d in donnees.get("failures") or []]
    version = mail_diagnostic.version_majeure(donnees.get("version"))
    afficher_liste(rapport, args, echecs, donnees, version)
    etat = types.SimpleNamespace(
        echecs=echecs, donnees=donnees, renvoi=None, plan=plan
    )
    return (CODE_RESTE if echecs else CODE_OK), etat


def selection_voulue(args, systeme, rapport, echecs):
    """La sélection à renvoyer, (mode, valeur), ou None : `--resend`
    confirmé par `--yes` ou au terminal, sinon le menu au terminal. Hors
    terminal, sans `--yes`, rien n'est renvoyé et le rapport le dit."""
    if args.selection:
        if args.yes:
            return args.selection
        if not systeme.interactif or args.json:
            rapport.attn(
                t("Nothing resent: re-run with --yes to confirm --resend.")
            )
            return None
        ids, _absents = choisir(echecs, *args.selection)
        if demander_oui(
            systeme, t("Resend {count} mail(s)? [y/N] ").format(count=len(ids))
        ):
            return args.selection
    elif not (args.list or args.json or not systeme.interactif):
        selection = menu(systeme, echecs)
        if selection is not None:
            return selection
    else:
        return None
    rapport.texte(t("No mail resent."))
    return None


def _renvoi(ids, absents, bilan=None, simulation=False):
    bilan = bilan or {}
    return {
        "requested": ids,
        "requeued": bilan.get("requeued") or [],
        "skipped": bilan.get("skipped") or [],
        "not_listed": absents,
        "method": bilan.get("method"),
        "dry_run": simulation,
    }


def executer(args, systeme, rapport):
    """Liste, sélection, renvoi : (code de sortie, état ou None)."""
    code, etat = lister(args, systeme, rapport)
    if etat is None or not etat.echecs:
        return code, etat
    selection = selection_voulue(args, systeme, rapport, etat.echecs)
    if selection is None:
        return CODE_RESTE, etat
    ids, absents = choisir(etat.echecs, *selection)
    if absents:
        rapport.attn(
            t("Not in the list, not resent: {ids}").format(
                ids=", ".join(f"#{i}" for i in absents)
            )
        )
    if not ids:
        rapport.texte(t("No mail resent."))
        return CODE_RESTE, etat
    if args.dry_run:
        simuler(etat.plan, rapport, ids)
        etat.renvoi = _renvoi(ids, absents, simulation=True)
        return CODE_RESTE, etat
    rapport.texte("")
    rapport.texte(
        t("Requeue {count} mail(s) through the Odoo shell…").format(
            count=len(ids)
        )
    )
    code, bilan = renvoyer(etat.plan, systeme, rapport, args, ids)
    if bilan is not None:
        etat.renvoi = _renvoi(ids, absents, bilan)
    if code == CODE_OK and absents:
        code = CODE_RESTE
    return code, etat


def demander_oui(systeme, question):
    """True sur y/yes/o/oui ; non sur tout le reste, fin de l'entrée et
    Ctrl-C compris."""
    try:
        reponse = systeme.demander(question).strip().lower()
    except (EOFError, KeyboardInterrupt):
        return False
    return reponse in ("y", "yes", "o", "oui")


def main(argv=None, systeme=None, rapport=None, flux=None):
    args = analyser(argv)
    flux = flux or sys.stdout
    systeme = systeme or Systeme(verbeux=args.verbose)
    if rapport is None:
        rapport = report.Rapport(flux=io.StringIO() if args.json else flux)
    try:
        code, etat = executer(args, systeme, rapport)
    except KeyboardInterrupt:
        rapport.erreur(t("Interrupted."))
        return CODE_INTERROMPU
    except Exception as err:
        # Python sortirait en 1, « échecs non renvoyés » : une erreur
        # imprévue est un refus, code 2.
        rapport.erreur(t("Unexpected error: {error}").format(error=err))
        if args.json:
            print(json.dumps({"exit_code": CODE_REFUS}), file=flux)
        return CODE_REFUS
    if args.json:
        if etat is None:
            print(
                json.dumps({"exit_code": code}, ensure_ascii=False), file=flux
            )
        else:
            print(
                json.dumps(
                    resume_json(
                        args,
                        etat.plan,
                        etat.echecs,
                        etat.donnees,
                        etat.renvoi,
                        code,
                    ),
                    ensure_ascii=False,
                    indent=2,
                ),
                file=flux,
            )
    return code


if __name__ == "__main__":
    sys.exit(main())
