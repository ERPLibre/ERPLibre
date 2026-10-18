#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Lire le journal d'une instance Odoo et dire ce qui est à revoir.

La source
---------
`--service UNITE`, ou l'unité détectée comme le fait `update_module.py`
(celle dont WorkingDirectory est ce checkout, sinon la seule active).
Quand la configuration de l'unité pose un `logfile`, Odoo y écrit et le
journal de systemd ne porte que les lignes de systemd : c'est ce fichier
qui est lu. Sinon, `journalctl -u UNITE -o short-iso --show-cursor`,
dont la sortie est lue au fil de l'eau, avec un délai total
(`--timeout`). `--file CHEMIN` lit un fichier donné, sans unité.

Une configuration que le compte ne peut pas lire laisse `logfile`
inconnu : un `--logfile` d'ExecStart est lu s'il y en a un, sinon le
journal, et une lecture du journal qui ne rend aucun enregistrement
d'Odoo refuse (code 2, conseil sudo) au lieu de dire « rien à revoir ».
Les notes du rapport passent aussi dans `source.notes` de `--json`.

La fenêtre
----------
- `--since-last` : depuis la dernière lecture. Le journal reprend après
  le curseur retenu (`--after-cursor`) ; un fichier reprend à l'octet
  retenu s'il garde le même inode et n'a pas raccourci, sinon il est relu
  depuis le début (rotation) et le rapport le dit. La première fois :
  les dernières 24 h.
- `--last HEURES` ; `--since "AAAA-MM-JJ[ hh:mm[:ss]]"` avec `--until`
  facultatif, en heure locale ; `--by-hour [--days N]` (7 par défaut),
  qui ajoute la matrice des erreurs par heure.
- Sans option de fenêtre : les dernières 24 h.

Les bornes passent à journalctl en secondes Unix (`--since @E`) ; pour un
fichier, elles filtrent les enregistrements par leur heure. Seul
`--since-last` lit et écrit l'état.

L'état
------
`<--state-dir>/<unité>.json` (`/var/lib/erplibre-logcheck` par défaut) :
`{"unit", "cursor", "updated"}` pour le journal, `{"path", "inode",
"offset", "updated"}` pour un fichier. Il n'est écrit qu'après une
lecture complète et réussie : une lecture refusée ne fait jamais perdre
une fenêtre. L'écriture passe par un fichier temporaire du même dossier
puis un renommage ; un état qui est un lien symbolique n'est ni lu ni
remplacé. Un dossier où le compte ne peut pas écrire n'empêche pas le
rapport : la position n'est pas retenue et le rapport le dit.

Le rapport
----------
Traces Python groupées par leur dernière ligne d'exception, autres
erreurs, requêtes SQL refusées, échecs d'envoi de courriel classés
(`lib_ops.mail_diagnostic`, cause passagère ou PERMANENTE, réglage à
regarder), bruit connu et motifs `--ignore` comptés à part. Seuls ERROR
et CRITICAL sont « à revoir ». `--json` rend le résumé de
`lib_ops.journal.resume_json`, aux clés anglaises jamais traduites.

Codes de sortie : 0 rien à revoir ; 1 quelque chose à revoir ; 2 lecture
impossible (droits, unité, fichier, options) ; 130 interrompu.

Lecture seule : rien n'est écrit hors du fichier d'état, aucune base
n'est lue. Root n'est pas exigé : un compte du groupe `systemd-journal`
(ou `adm`) lit le journal de l'unité ; sans ce droit, journalctl ne
montre que les messages du compte, et le programme le détecte et
conseille sudo au lieu de dire « rien à revoir ».

Bibliothèque standard seulement, sans syntaxe postérieure à Python 3.7 :
le programme se lance aussi par le python3 d'un serveur de production.
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import io
import json
import os
import re
import sys
import time
import types

sys.path.append(
    os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))
)

from script.database import odoo_backup  # noqa: E402
from script.lib_ops import (  # noqa: E402
    journal,
    mail_diagnostic,
    odoo_instance,
    report,
    service,
    systemd,
)

try:
    from script.todo.todo_i18n import t
except Exception:  # pragma: no cover - repli si i18n indisponible

    def t(key: str) -> str:
        return key


RACINE = os.path.normpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")
)

CODE_RIEN = 0
CODE_A_REVOIR = 1
CODE_REFUS = 2
CODE_INTERROMPU = 130

ETAT_PAR_DEFAUT = "/var/lib/erplibre-logcheck"
FENETRE_PAR_DEFAUT = 24
JOURS_PAR_DEFAUT = 7
JOURS_MAX = 3650
DELAI_LECTURE = 300
TOP_PAR_DEFAUT = 15
LIGNES_ECHANTILLON = 15
IDS_MONTRES = 10
MODE_ETAT = 0o644
BLOC = 1024 * 1024

# Ce que journalctl écrit sur stderr quand le compte ne voit pas le
# journal du système : le code de sortie reste souvent 0, et la sortie
# vide passerait pour « rien à revoir ».
INDICES_DROITS = (
    "not seeing messages from other users",
    "insufficient permissions",
    "No journal files were",
)

N_ = service.N_
Refus = service.Refus

# Libellés du bruit connu, par identifiant de `journal.BRUIT_CONNU`.
LIBELLES_BRUIT = {
    "sourcemap": N_("Source map (.map) of an outdated asset bundle"),
    "serialization_retry": N_(
        "Concurrent update conflict, retried by Odoo (bad query)"
    ),
    "vapid": N_("Push subscription with an outdated VAPID key"),
}


class Systeme(odoo_backup.Systeme):
    """Les effets de bord : systemctl (`lanceur`), journalctl en flux,
    l'horloge. Un test en dérive une classe et rien de réel n'est lancé."""

    def lire_journal(self, argv, recevoir, delai):
        """Lance `argv` et passe chaque ligne de sa sortie à `recevoir` :
        (code, stderr, tué). Un binaire absent rend 127."""
        env = os.environ.copy()
        env["SYSTEMD_COLORS"] = "0"
        env["SYSTEMD_PAGER"] = ""
        decoupe = Morceleur(recevoir)
        try:
            code, erreurs, tue = self.flux(argv, env, decoupe, delai)
        except OSError as err:
            return 127, str(err), False
        decoupe.finir()
        return code, erreurs, tue


class Morceleur:
    """Découpe des blocs d'octets en lignes de texte pour `recevoir`.

    Une ligne de plus de `journal.LIGNE_MAX` octets est rendue coupée, et
    sa suite jusqu'au saut de ligne est perdue : la mémoire ne grossit pas
    avec une ligne démesurée. `reste` porte la fin d'une ligne non encore
    terminée ; `finir()` la rend telle quelle.
    """

    def __init__(self, recevoir):
        self.recevoir = recevoir
        self.reste = b""
        self.coupe = False

    def __call__(self, bloc):
        morceaux = (self.reste + bloc).split(b"\n")
        self.reste = morceaux.pop()
        for brut in morceaux:
            if self.coupe:
                self.coupe = False
                continue
            self.recevoir(brut.decode("utf-8", "replace"))
        if len(self.reste) > journal.LIGNE_MAX:
            if not self.coupe:
                self.recevoir(
                    self.reste[: journal.LIGNE_MAX].decode("utf-8", "replace")
                )
                self.coupe = True
            self.reste = b""

    def finir(self):
        if self.reste and not self.coupe:
            self.recevoir(self.reste.decode("utf-8", "replace"))
        self.reste = b""


def lire_fichier(chemin, depuis, recevoir, garder_fin=True):
    """Lit `chemin` à partir de l'octet `depuis` et passe chaque ligne à
    `recevoir` : (inode, fin), `fin` étant l'octet où reprendre.

    Une dernière ligne sans saut de ligne est une écriture en cours :
    `garder_fin` faux ne la lit pas, et `fin` s'arrête devant elle pour
    que la lecture suivante la prenne entière. Lève OSError.
    """
    with open(chemin, "rb") as fichier:
        info = os.fstat(fichier.fileno())
        fichier.seek(depuis)
        decoupe = Morceleur(recevoir)
        lus = 0
        while True:
            bloc = fichier.read(BLOC)
            if not bloc:
                break
            lus += len(bloc)
            decoupe(bloc)
        fin = depuis + lus
        if garder_fin:
            decoupe.finir()
        elif not decoupe.coupe:
            fin -= len(decoupe.reste)
        return info.st_ino, fin


# --- État ------------------------------------------------------------------


def nom_etat(source):
    """Le nom du fichier d'état : l'unité, sinon `file-<nom>-<empreinte>`
    du chemin lu, qui ne contient que des caractères sûrs."""
    if source.unite:
        return source.unite + ".json"
    nom = re.sub(r"[^A-Za-z0-9_.-]", "_", os.path.basename(source.chemin))
    empreinte = hashlib.sha256(source.chemin.encode("utf-8")).hexdigest()
    return f"file-{nom}-{empreinte[:12]}.json"


def lire_etat(chemin):
    """(état, raison) : le dict d'état, {} s'il manque ou ne se lit pas ;
    `raison` dit pourquoi il est ignoré, "" sinon. Un lien symbolique
    n'est pas suivi."""
    if os.path.islink(chemin):
        return {}, t("{path} is a symbolic link: refused.").format(path=chemin)
    try:
        return odoo_backup.lire_etat(chemin), ""
    except OSError as err:
        return {}, str(err.strerror or err)


def ecrire_etat(chemin, donnees):
    """Écrit l'état ; rend "" s'il est écrit, sinon la raison.

    Le dossier manquant est créé (0755). Un lien symbolique à la place du
    fichier refuse : `os.replace` le remplacerait sans le suivre, mais il
    dit qu'un autre compte a la main sur ce nom."""
    dossier = os.path.dirname(chemin)
    try:
        if not os.path.isdir(dossier):
            os.makedirs(dossier, 0o755)
        if os.path.islink(chemin):
            return t("{path} is a symbolic link: refused.").format(path=chemin)
        texte = json.dumps(donnees, indent=2, sort_keys=True) + "\n"
        odoo_backup._ecrire_atomique(
            chemin,
            ".logcheck.",
            texte,
            MODE_ETAT,
            types.SimpleNamespace(root=False),
            None,
        )
    except OSError as err:
        return f"{dossier}: {err.strerror or err}"
    return ""


# --- Source et fenêtre -----------------------------------------------------


def version_odoo(plan, config):
    """La version majeure d'Odoo de l'instance, ou None : `.odoo-version`
    du dossier de travail, sinon `odooNN.0` dans ExecStart ou
    l'addons_path."""
    try:
        with open(os.path.join(plan.wd, ".odoo-version")) as fichier:
            version = mail_diagnostic.version_majeure(fichier.read())
            if version:
                return version
    except (OSError, TypeError):
        pass
    textes = list(getattr(plan, "execstart", []) or []) + [
        str((config or {}).get("addons_path", ""))
    ]
    for texte in textes:
        trouve = re.search(r"odoo(\d+)\.0", texte)
        if trouve:
            return int(trouve.group(1))
    return None


def determiner_source(args, systeme):
    """La source à lire : `kind` (journal ou file), `unite`, `chemin`,
    `version`, `notes` (lignes à afficher), `config_illisible` (le
    message du refus de lire la configuration, "" sinon). Refus sur ce
    qui manque."""
    source = types.SimpleNamespace(
        kind="journal",
        unite="",
        chemin="",
        version=None,
        notes=[],
        meme_compte=False,
        config_illisible="",
    )
    if args.file:
        source.kind = "file"
        source.chemin = os.path.abspath(args.file)
        return source
    plan = types.SimpleNamespace()
    props = service.detecter_unite(args.service, systeme, RACINE, plan)
    source.unite = plan.unite
    try:
        service.detecter_compte_et_dossier(None, systeme, plan, props)
        source.meme_compte = plan.utilisateur == plan.courant
        config = service.detecter_config(None, plan)
    except Refus as err:
        # Sans configuration lisible, seul `--logfile` d'ExecStart dit
        # encore où Odoo écrit ; un chemin relatif sans dossier de travail
        # connu ne se résout pas. Sinon le journal est lu, mais un
        # `logfile` de la configuration le laisserait sans ligne d'Odoo :
        # `config_illisible` fait refuser une lecture qui n'en rend
        # aucune (`lire_le_journal`).
        wd = getattr(plan, "wd", None) or ""
        logfile = odoo_instance.fichier_journal(
            getattr(plan, "execstart", None) or [], {}, wd
        )
        if logfile and os.path.isabs(logfile):
            source.kind = "file"
            source.chemin = logfile
            source.version = version_odoo(plan, {})
            return source
        source.config_illisible = err.message(t)
        source.notes.append(
            t(
                "Odoo configuration not read ({error}): the journal is read."
            ).format(error=source.config_illisible)
        )
        return source
    source.version = version_odoo(plan, config)
    logfile = odoo_instance.fichier_journal(plan.execstart, config, plan.wd)
    if logfile:
        source.kind = "file"
        source.chemin = logfile
    return source


def epoque_locale(texte):
    """Les secondes Unix d'une date locale `AAAA-MM-JJ[ hh:mm[:ss]]`.
    Lève ValueError."""
    texte = " ".join((texte or "").split())
    for forme in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return time.mktime(time.strptime(texte, forme))
        except ValueError:
            continue
    raise ValueError(texte)


def calculer_fenetre(args, maintenant):
    """La fenêtre : `mode`, `depuis`, `jusqu` (secondes Unix ou None),
    `incremental`. Lève ValueError sur une date illisible."""
    fenetre = types.SimpleNamespace(
        mode="last-hours",
        depuis=None,
        jusqu=None,
        incremental=False,
        maintenant=maintenant,
    )
    if args.since_last:
        fenetre.mode = "since-last"
        fenetre.incremental = True
    elif args.by_hour:
        fenetre.mode = "by-hour"
        fenetre.depuis = maintenant - args.days * 86400
    elif args.since:
        fenetre.mode = "range"
        fenetre.depuis = epoque_locale(args.since)
        if args.until:
            fenetre.jusqu = epoque_locale(args.until)
    else:
        heures = args.last or FENETRE_PAR_DEFAUT
        fenetre.depuis = maintenant - heures * 3600
    return fenetre


def _iso_epoque(epoque):
    if epoque is None:
        return ""
    return journal.iso(
        datetime.datetime.fromtimestamp(epoque)
        .astimezone()
        .replace(microsecond=0)
    )


# --- Lecture ---------------------------------------------------------------


class Lecture:
    """Le résultat d'une lecture : l'Analyse, l'état à écrire (ou None),
    les notes à afficher. `erreur` non vide : la lecture a échoué."""

    def __init__(self, analyse):
        self.analyse = analyse
        self.etat = None
        self.notes = []
        self.erreur = ""


def conseil_droits():
    return t("run with sudo, or add the user to the systemd-journal group.")


def _entier(valeur):
    """`valeur` en entier positif ou nul, sinon None. Un état modifié à
    la main ou tronqué ne fait pas échouer la lecture : la valeur
    illisible vaut une valeur absente."""
    if isinstance(valeur, bool):
        return None
    try:
        nombre = int(valeur)
    except (TypeError, ValueError, OverflowError):
        return None
    return nombre if nombre >= 0 else None


def _reprise_du_journal(systeme, fenetre, etat, lecture):
    """Le curseur où reprendre (`--since-last`), ou None. Sans curseur
    lisible, `fenetre.depuis` devient l'heure `updated` de l'état, sinon
    les dernières 24 h (première lecture, notée dans `lecture`)."""
    if not fenetre.incremental:
        return None
    curseur = etat.get("cursor")
    if isinstance(curseur, str) and curseur:
        return curseur
    depuis = _entier(etat.get("updated"))
    if depuis:
        fenetre.depuis = depuis
    else:
        fenetre.depuis = systeme.maintenant() - FENETRE_PAR_DEFAUT * 3600
        lecture.notes.append(t("First run: last 24 h."))
    return None


def lire_le_journal(args, systeme, source, fenetre, etat, analyse):
    lecture = Lecture(analyse)
    curseur = _reprise_du_journal(systeme, fenetre, etat, lecture)
    argv = systemd.commande_journal(
        source.unite, fenetre.depuis, fenetre.jusqu, curseur
    )
    if args.verbose:
        print(f"+ {service.joindre(argv)}", file=sys.stderr, flush=True)
    decoupeur = journal.Decoupeur()

    def recevoir(ligne):
        fini = decoupeur.ajouter(ligne)
        if fini is not None:
            analyse.ajouter(fini)

    debut = systeme.maintenant()
    code, erreurs, tue = systeme.lire_journal(argv, recevoir, args.timeout)
    fini = decoupeur.finir()
    if fini is not None:
        analyse.ajouter(fini)
    if code == 127:
        lecture.erreur = t("journalctl not found: {error}").format(
            error=erreurs.strip()
        )
    elif tue:
        lecture.erreur = t(
            "The journal read exceeded {seconds} s (--timeout)."
        ).format(seconds=args.timeout)
    elif any(indice in erreurs for indice in INDICES_DROITS):
        # Un compte ordinaire voit, malgré l'avertissement, les messages de
        # ses propres processus : sous le compte de l'unité, ceux de
        # l'unité. La lecture n'est admise que si elle a rendu au moins un
        # enregistrement ; une sortie vide ne distingue pas « rien de
        # neuf » de « rien de visible », et dirait à tort « rien à revoir ».
        if source.meme_compte and code == 0 and analyse.enregistrements:
            lecture.notes.append(
                t(
                    "Only the messages of this account are visible: those of"
                    " the unit, which runs under it."
                )
            )
        else:
            lecture.erreur = t(
                "This account cannot read the journal of {unit}: {advice}"
            ).format(unit=source.unite, advice=conseil_droits())
    if lecture.erreur:
        return lecture
    if code != 0:
        lecture.erreur = t("journalctl failed (code {code}): {error}").format(
            code=code, error=" ".join(erreurs.split())[:300]
        )
    elif source.config_illisible and not analyse.enregistrements:
        # Aucune ligne d'Odoo : rien de neuf, ou un `logfile` posé dans la
        # configuration non lue. « Rien à revoir » serait un faux
        # négatif.
        lecture.erreur = t(
            "{error} The journal holds no Odoo record in this window: Odoo"
            " may write to a logfile set in that configuration."
        ).format(error=source.config_illisible)
    if lecture.erreur:
        return lecture
    if fenetre.incremental:
        lecture.etat = {
            "unit": source.unite,
            "cursor": decoupeur.curseur or curseur,
            "updated": int(debut),
        }
    return lecture


def lire_le_fichier(args, systeme, source, fenetre, etat, analyse):
    lecture = Lecture(analyse)
    depart = 0
    if fenetre.incremental:
        try:
            info = os.stat(source.chemin)
        except OSError as err:
            lecture.erreur = t("Cannot read {path}: {error}").format(
                path=source.chemin, error=err.strerror or err
            )
            return lecture
        offset = _entier(etat.get("offset"))
        if etat.get("path") == source.chemin and offset is not None:
            if (
                _entier(etat.get("inode")) == info.st_ino
                and offset <= info.st_size
            ):
                depart = offset
            else:
                lecture.notes.append(
                    t(
                        "{path} was rotated or truncated: read from the start."
                    ).format(path=source.chemin)
                )
        else:
            analyse.depuis = systeme.maintenant() - FENETRE_PAR_DEFAUT * 3600
            lecture.notes.append(t("First run: last 24 h."))
    else:
        analyse.depuis, analyse.jusqu = fenetre.depuis, fenetre.jusqu
    decoupeur = journal.Decoupeur()

    def recevoir(ligne):
        fini = decoupeur.ajouter(ligne)
        if fini is not None:
            analyse.ajouter(fini)

    try:
        inode, fin = lire_fichier(
            source.chemin, depart, recevoir, not fenetre.incremental
        )
    except OSError as err:
        lecture.erreur = t("Cannot read {path}: {error}").format(
            path=source.chemin, error=err.strerror or err
        )
        if isinstance(err, PermissionError):
            lecture.erreur += " " + t("Run with sudo.")
        return lecture
    fini = decoupeur.finir()
    if fini is not None:
        analyse.ajouter(fini)
    if fenetre.incremental:
        lecture.etat = {
            "path": source.chemin,
            "inode": inode,
            "offset": fin,
            "updated": int(systeme.maintenant()),
        }
    return lecture


# --- Rapport texte ---------------------------------------------------------


def _heure(moment):
    return moment.strftime("%Y-%m-%d %H:%M:%S") if moment else ""


def _groupes(rapport, modele, groupes, top, detail):
    """Une section de groupes : titre (`modele` avec le nombre
    d'enregistrements et de groupes), puis au plus `top` groupes, chacun
    `[Nx] titre` suivi des lignes que rend `detail(groupe)`."""
    if not groupes:
        return
    rapport.texte("")
    rapport.texte(
        t(modele).format(
            count=sum(g.nombre for g in groupes), groups=len(groupes)
        )
    )
    for g in groupes[:top]:
        rapport.texte(f"  [{g.nombre}x] {g.titre}")
        for ligne in detail(g):
            rapport.texte("        " + ligne)
    if len(groupes) > top:
        rapport.texte(
            "  "
            + t("+{count} more group(s) (--top).").format(
                count=len(groupes) - top
            )
        )


def _section_courriels(rapport, courriels, version):
    if not courriels:
        return
    rapport.texte("")
    rapport.texte(t("[4] Mail sending failures"))
    for g in courriels:
        nature = t("PERMANENT") if g.classe.permanent else t("transient")
        rapport.texte(f"  [{g.nombre}x] {t(g.classe.libelle)} — {nature}")
        rapport.texte(f"        {_heure(g.premier)} – {_heure(g.dernier)}")
        if g.ids:
            ids = sorted(g.ids)
            texte = ", ".join(f"#{i}" for i in ids[:IDS_MONTRES])
            if len(ids) > IDS_MONTRES:
                texte += f" +{len(ids) - IDS_MONTRES}"
            rapport.texte("        " + t("Mails: {ids}").format(ids=texte))
        reglage = t(mail_diagnostic.reglage(g.classe.id, version))
        rapport.texte(
            "        " + t("Check: {setting}").format(setting=reglage)
        )
    rapport.texte(
        "  "
        + t("List and resend the failed mails: {command}").format(
            command="script/odoo/mail_retry.py"
        )
    )


def _section_bruit(rapport, ignores):
    if not ignores:
        return
    rapport.texte("")
    rapport.texte(t("[5] Ignored as known noise"))
    for etiquette, nombre in sorted(
        ignores.items(), key=lambda e: (-e[1], e[0])
    ):
        libelle = LIBELLES_BRUIT.get(etiquette)
        rapport.texte(f"  [{nombre}x] {t(libelle) if libelle else etiquette}")


def _section_horaire(rapport, analyse, fenetre):
    rapport.texte("")
    rapport.texte(t("[6] Errors per hour (local time)"))
    jours = jours_de(fenetre.depuis, fenetre.jusqu or fenetre.maintenant)
    lignes = journal.tableau_horaire(
        analyse.par_heure, jours, t("hour"), t("total")
    )
    if not lignes:
        rapport.texte("  " + t("No error in this window."))
        return
    for ligne in lignes:
        rapport.texte("  " + ligne)
    heures = {h for (j, h), n in analyse.par_heure.items() if n and j in jours}
    if len(heures) < 24:
        rapport.texte(
            "  "
            + t("Hours without errors: {ranges}").format(
                ranges=journal.plages_sans(heures)
            )
        )


def _entete(rapport, args, source, fenetre, lecture):
    origine = source.unite or source.chemin
    if source.kind == "file" and source.unite:
        origine = f"{source.unite} ({source.chemin})"
    rapport.texte(t("Odoo journal: {source}").format(source=origine))
    if fenetre.mode == "since-last":
        texte = t("since the last check")
    elif fenetre.mode == "by-hour":
        texte = t("errors per hour over {days} day(s)").format(days=args.days)
    else:
        texte = "{} → {}".format(
            _iso_epoque(fenetre.depuis) or "…",
            _iso_epoque(fenetre.jusqu) or t("now"),
        )
    rapport.champ(t("Window"), texte)
    for note in source.notes + lecture.notes:
        rapport.texte("  " + note)
    rapport.champ(t("Records"), str(lecture.analyse.enregistrements))


def ecrire_texte(rapport, args, source, fenetre, lecture, etat_ecrit):
    """Le rapport lisible : fenêtre, sections non vides, verdict."""
    analyse = lecture.analyse
    _entete(rapport, args, source, fenetre, lecture)

    def trace(g):
        lignes = [
            f"{_heure(g.premier)} – {_heure(g.dernier)}"
            f" · {g.logger} · {g.base}"
        ]
        echantillon = g.echantillon
        if not args.full_trace:
            echantillon = echantillon[: LIGNES_ECHANTILLON + 1]
        return lignes + [f"| {ligne}" for ligne in echantillon]

    def erreur(g):
        return [
            f"{_heure(g.premier)} – {_heure(g.dernier)} · {g.base}",
            f"| {g.echantillon[0]}",
        ]

    def requete(g):
        return [f"{_heure(g.premier)} – {_heure(g.dernier)} · {g.base}"]

    _groupes(
        rapport,
        N_("[1] Python tracebacks: {count} in {groups} group(s)"),
        analyse.groupes_tracebacks(),
        args.top,
        trace,
    )
    _groupes(
        rapport,
        N_("[2] Errors: {count} in {groups} group(s)"),
        analyse.groupes_erreurs(),
        args.top,
        erreur,
    )
    _groupes(
        rapport,
        N_("[3] Refused SQL queries: {count} in {groups} group(s)"),
        analyse.groupes_sql(),
        args.top,
        requete,
    )
    _section_courriels(rapport, analyse.groupes_courriels(), source.version)
    _section_bruit(rapport, analyse.ignores)
    if fenetre.mode == "by-hour":
        _section_horaire(rapport, analyse, fenetre)
    rapport.texte("")
    if analyse.a_revoir:
        rapport.attn(
            t("{count} record(s) to review.").format(count=analyse.a_revoir)
        )
    else:
        rapport.ok(t("Nothing to review."))
    if fenetre.incremental and etat_ecrit:
        rapport.attn(
            t("Position not saved: {reason}").format(reason=etat_ecrit)
        )


def jours_de(depuis, jusqu):
    """Les jours locaux de la fenêtre, de `depuis` à `jusqu` (secondes
    Unix) compris."""
    fin = datetime.date.fromtimestamp(jusqu)
    jour = datetime.date.fromtimestamp(depuis) if depuis else fin
    jours = []
    while jour <= fin:
        jours.append(jour.strftime("%Y-%m-%d"))
        jour += datetime.timedelta(days=1)
    return jours


# --- Programme -------------------------------------------------------------

TYPES = service.types_argparse(t)


def _type_regex(valeur):
    try:
        return re.compile(valeur)
    except re.error as err:
        raise argparse.ArgumentTypeError(
            t("invalid regular expression: {error}").format(error=err)
        )


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
            "Read the journal of an Odoo instance: tracebacks, errors,"
            " refused SQL queries and mail sending failures to review."
        )
    )
    source = parser.add_mutually_exclusive_group()
    source.add_argument(
        "--service",
        type=TYPES.unite,
        help=t(
            "systemd unit; default: the unit whose WorkingDirectory is this"
            " checkout, else the only active one."
        ),
    )
    source.add_argument(
        "--file",
        help=t("Odoo log file to read instead of a unit."),
    )
    fenetre = parser.add_mutually_exclusive_group()
    fenetre.add_argument(
        "--since-last",
        action="store_true",
        help=t("Since the last check (position kept in --state-dir)."),
    )
    fenetre.add_argument(
        "--last",
        type=TYPES.secondes,
        metavar="HOURS",
        help=t("The last HOURS hours."),
    )
    fenetre.add_argument(
        "--since",
        metavar="DATE",
        help=t("From this local date: YYYY-MM-DD[ HH:MM[:SS]]."),
    )
    fenetre.add_argument(
        "--by-hour",
        action="store_true",
        help=t("Errors per hour over --days days."),
    )
    parser.add_argument(
        "--until",
        metavar="DATE",
        help=t("With --since: up to this local date."),
    )
    parser.add_argument(
        "--days",
        type=_type_jours,
        default=JOURS_PAR_DEFAUT,
        help=t("Days of --by-hour; default: {days}.").format(
            days=JOURS_PAR_DEFAUT
        ),
    )
    parser.add_argument(
        "--ignore",
        action="append",
        type=_type_regex,
        default=[],
        metavar="REGEX",
        help=t(
            "Records whose header line or final exception matches REGEX"
            " are not to review; repeatable."
        ),
    )
    parser.add_argument(
        "--state-dir",
        default=ETAT_PAR_DEFAUT,
        help=t("State directory; default: {path}.").format(
            path=ETAT_PAR_DEFAUT
        ),
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help=t("Print the summary as JSON (untranslated keys)."),
    )
    parser.add_argument(
        "--full-trace",
        action="store_true",
        help=t("Show every line of each traceback sample."),
    )
    parser.add_argument(
        "--top",
        type=TYPES.secondes,
        default=TOP_PAR_DEFAUT,
        metavar="N",
        help=t("Groups shown per section; default: {count}.").format(
            count=TOP_PAR_DEFAUT
        ),
    )
    parser.add_argument(
        "--timeout",
        type=TYPES.secondes,
        default=DELAI_LECTURE,
        help=t(
            "Maximum seconds for the journal read; default: {seconds}."
        ).format(seconds=DELAI_LECTURE),
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help=t("Show each system command on stderr."),
    )
    args = parser.parse_args(argv)
    if args.until and not args.since:
        parser.error(t("--until requires --since."))
    return args


def _json_echec(code, message):
    return json.dumps(
        {"version": 1, "exit_code": code, "error": message},
        ensure_ascii=False,
    )


def executer(args, systeme, flux):
    rapport = report.Rapport(
        flux=io.StringIO() if args.json else flux, couleur=None
    )
    try:
        source = determiner_source(args, systeme)
        fenetre = calculer_fenetre(args, systeme.maintenant())
    except Refus as err:
        return _refuser(args, flux, err.message(t))
    except ValueError as err:
        return _refuser(
            args, flux, t("Invalid date: {value}").format(value=err)
        )
    analyse = journal.Analyse(args.ignore, True)
    chemin_etat = os.path.join(
        os.path.abspath(args.state_dir), nom_etat(source)
    )
    etat, raison_etat = {}, ""
    if fenetre.incremental:
        etat, raison_etat = lire_etat(chemin_etat)
    lire = lire_le_journal if source.kind == "journal" else lire_le_fichier
    lecture = lire(args, systeme, source, fenetre, etat, analyse)
    if lecture.erreur:
        return _refuser(args, flux, lecture.erreur)
    etat_ecrit = None
    if lecture.etat is not None:
        etat_ecrit = raison_etat or ecrire_etat(chemin_etat, lecture.etat)
    code = CODE_A_REVOIR if analyse.a_revoir else CODE_RIEN
    if args.json:
        resume = journal.resume_json(
            analyse,
            source={
                "kind": source.kind,
                "unit": source.unite,
                "path": source.chemin,
                "notes": source.notes + lecture.notes,
            },
            fenetre={
                "mode": fenetre.mode,
                "since": _iso_epoque(fenetre.depuis),
                "until": _iso_epoque(fenetre.jusqu),
            },
            etat={
                "saved": etat_ecrit == "",
                "path": chemin_etat if fenetre.incremental else "",
                "reason": etat_ecrit or "",
            },
            code=code,
            version=source.version,
        )
        print(json.dumps(resume, ensure_ascii=False, indent=2), file=flux)
        return code
    ecrire_texte(rapport, args, source, fenetre, lecture, etat_ecrit)
    return code


def _refuser(args, flux, message):
    if args.json:
        print(_json_echec(CODE_REFUS, message), file=flux)
    print(f"❌ {message}", file=sys.stderr)
    return CODE_REFUS


def main(argv=None, systeme=None, flux=None):
    args = analyser(argv)
    systeme = systeme or Systeme(verbeux=args.verbose)
    try:
        return executer(args, systeme, flux or sys.stdout)
    except KeyboardInterrupt:
        print(t("Interrupted."), file=sys.stderr)
        return CODE_INTERROMPU
    except Exception as err:
        # Python sortirait en 1, « à revoir » : une erreur imprévue est
        # une lecture impossible, code 2.
        return _refuser(
            args,
            flux or sys.stdout,
            t("Unexpected error: {error}").format(error=err),
        )


if __name__ == "__main__":
    sys.exit(main())
