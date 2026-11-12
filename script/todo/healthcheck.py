#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Le healthcheck du TODO : des vérifications à sec du checkout.

Aucune vérification n'écrit dans le checkout ni ne touche au réseau : elles
lisent git, lancent black, isort et mmg en mode vérification, et sondent des
ports locaux. Chacune note les commandes qu'elle lance, que le rapport
affiche au-dessus de son verdict ; un sommaire ferme le rapport.

Deux portées règlent ce qui est examiné :

- les FICHIERS (formatage, hygiène des commentaires, docs) : ceux qui ne sont
  pas commités, ceux qui diffèrent de la branche de base depuis leur point
  de divergence, commités ou non, ou tous les fichiers suivis ;
- les DÉPÔTS (conflits, non commités, non poussés, formatage) : le checkout
  ERPLibre seul, ou avec chaque dépôt d'addons du manifeste local.

La branche de base est « master » pour ERPLibre ; pour un dépôt d'addons,
c'est la cible que le manifeste local lui donne (voir
`repo_state.ref_cible`), car ces dépôts n'ont pas de « master » commun.

Une vérification qui lève rend un échec à son nom et laisse passer les
suivantes.

Une vérification peut joindre des résolutions à son verdict : le rapport les
explique après le sommaire, et le menu les offre comme entrées. Elles seules
écrivent ou touchent au réseau, et seulement une fois lancées et confirmées
(voir `executer_resolution`).
"""

import copy
import json
import os
import re
import shlex
import shutil
import socket
import subprocess
import tempfile
import threading
import time
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

from script.git import freeze_resolution
from script.poetry import poetry_venv_drift as drift
from script.todo import (
    container_runtime,
    todo_couleur,
    todo_etat,
    todo_journal,
)
from script.todo.todo_i18n import t

OK = "ok"
INFO = "info"
ALERTE = "alerte"
ECHEC = "echec"
SAUTE = "saute"
ICONES = {
    OK: "✅",
    INFO: "ℹ️ ",
    ALERTE: "⚠️ ",
    ECHEC: "❌",
    SAUTE: "⏭️ ",
}
# Ordre du décompte du sommaire.
ORDRE_STATUTS = (OK, INFO, ALERTE, ECHEC, SAUTE)

FICHIERS_NON_COMMITES = "non_commites"
FICHIERS_DEPUIS_BASE = "depuis_base"
FICHIERS_TOUS = "tous"
PORTEES_FICHIERS = (
    FICHIERS_NON_COMMITES,
    FICHIERS_DEPUIS_BASE,
    FICHIERS_TOUS,
)
DEPOTS_ERPLIBRE = "erplibre"
DEPOTS_TOUS = "tous"
PORTEES_DEPOTS = (DEPOTS_ERPLIBRE, DEPOTS_TOUS)

BRANCHE_BASE_ERPLIBRE = "master"
VENV_ERPLIBRE = ".venv.erplibre"
# Le nombre de fichiers passés à black ou à isort par appel : une liste
# entière du cœur d'Odoo dépasse la longueur de ligne de commande permise.
LOT_FICHIERS = 200
# Les lignes de détail qu'une vérification affiche au plus ; le compte, lui,
# porte sur tout.
MAX_DETAILS = 15
DELAI_GIT = 30
DELAI_OUTIL = 600
# Sous ces seuils d'espace libre sur la partition du checkout, l'alerte puis
# l'échec : une installation d'Odoo et ses venvs demandent plusieurs Gio.
DISQUE_ALERTE = 5 * 1024**3
DISQUE_ECHEC = 1024**3
# Les traces qu'une opération git interrompue laisse dans le dossier .git.
OPERATIONS_GIT = (
    ("MERGE_HEAD", "merge"),
    ("rebase-merge", "rebase"),
    ("rebase-apply", "rebase"),
    ("CHERRY_PICK_HEAD", "cherry-pick"),
    ("REVERT_HEAD", "revert"),
)
RE_SUIVI = re.compile(r"ahead (\d+)")
# Au-delà, les journaux de session pèsent assez pour qu'on le dise : une
# installation d'Odoo journalisée en entier en fait des dizaines de Mio.
JOURNAUX_ALERTE = 1024**3


@dataclass
class Resolution:
    """Ce qu'on peut faire d'un écart qu'une vérification a trouvé.

    `cle` nomme l'action d'`executer_resolution` (une constante de
    `freeze_resolution`) ; None pour une résolution qui ne fait qu'expliquer
    ce qui reste à faire à la main. `libelle` est l'entrée du menu,
    `lignes` l'explication du rapport, `depots` les entrées de
    `repo_state` visées."""

    cle: object
    libelle: str
    lignes: list
    depots: list = field(default_factory=list)

    @property
    def actionnable(self):
        return self.cle is not None


@dataclass
class Resultat:
    """Le verdict d'une vérification, les commandes qui l'ont produit et
    les résolutions qu'il propose."""

    titre: str
    statut: str
    resume: str
    details: list = field(default_factory=list)
    commandes: list = field(default_factory=list)
    resolutions: list = field(default_factory=list)


# Le titre de chaque vérification, clé de traduction, par nom de fonction :
# le rapport et le menu le lisent au même endroit.
TITRES = {
    "verifier_conflits": "Git conflict in progress",
    "verifier_non_commites": "Uncommitted files",
    "verifier_non_pousses": "Unpushed commits",
    "verifier_formatage": "Python formatting",
    "verifier_hygiene": "Comment hygiene",
    "verifier_docs": "Docs to regenerate (mmg)",
    "verifier_manifeste": "Addons against the manifest",
    "verifier_branches": "Repo branches",
    "verifier_hooks": "Git hooks",
    "verifier_venv": "Odoo venv",
    "verifier_dependances_venvs": "Venv dependencies",
    "verifier_disque": "Free disk space",
    "verifier_postgresql": "PostgreSQL",
    "verifier_odoo": "Odoo HTTP port",
    "verifier_commandes_claude": "Claude commands",
    "verifier_journaux": "TODO session logs",
}


# L'icône de chaque vérification, devant son titre dans le menu, le rapport
# et le sommaire. Un seul point de code par icône, sans sélecteur de
# variante : le sommaire aligne les titres par leur longueur en caractères,
# et une icône à deux points de code y décalerait sa ligne.
ICONES_VERIFICATIONS = {
    "verifier_conflits": "💥",
    "verifier_non_commites": "📝",
    "verifier_non_pousses": "📤",
    "verifier_formatage": "🐍",
    "verifier_hygiene": "🧼",
    "verifier_docs": "📚",
    "verifier_manifeste": "🧩",
    "verifier_branches": "🌿",
    "verifier_hooks": "🪝",
    "verifier_venv": "🧪",
    "verifier_dependances_venvs": "📦",
    "verifier_disque": "💾",
    "verifier_postgresql": "🐘",
    "verifier_odoo": "🌐",
    "verifier_commandes_claude": "🤖",
    "verifier_journaux": "📜",
}


def titre(verification):
    """Le titre traduit d'une vérification, précédé de son icône."""
    nom = verification.__name__
    return f"{ICONES_VERIFICATIONS[nom]} {t(TITRES[nom])}"


class _Caches:
    """Ce que les vérifications d'une même passe calculent une fois et se
    partagent : la liste des dépôts, le `git status` de chacun, le relevé
    de `repo_state`. Le verrou sérialise chaque calcul, si bien que deux
    vérifications parallèles qui demandent la même chose n'en lancent
    qu'un."""

    def __init__(self):
        self.verrou = threading.RLock()
        self.depots = None
        self.status = {}
        self.snapshot = None


class Contexte:
    """Ce que les vérifications partagent : racine, portées, commandes.

    `etat_commande_claude(deploye, gabarit)` rend l'état d'une commande
    Claude déployée, tel que le TODO le calcule ; `commandes_claude` est
    {nom: fichier du gabarit dans conf/}. Les deux viennent du TODO, qui
    sait comparer en ignorant les lignes d'identité git.
    """

    def __init__(
        self,
        racine,
        fichiers=FICHIERS_NON_COMMITES,
        depots=DEPOTS_ERPLIBRE,
        etat_commande_claude=None,
        commandes_claude=None,
    ):
        self.racine = os.path.abspath(racine)
        self.portee_fichiers = fichiers
        self.portee_depots = depots
        self.etat_commande_claude = etat_commande_claude
        self.commandes_claude = commandes_claude or {}
        self._verrou = threading.Lock()
        self._commandes = None
        self._depots_notes = False
        self._caches = _Caches()
        # Le tampon de commandes d'un fil lancé par `en_parallele`.
        self._fil = threading.local()

    def pour_verification(self):
        """Un contexte pour une vérification lancée en parallèle des
        autres : son propre relevé de commandes, les caches de la passe
        partagés. Une commande dont le résultat vient du cache est notée
        quand même : le rapport de chaque vérification ne dépend pas de
        celle qui a calculé la première."""
        sous = copy.copy(self)
        sous._verrou = threading.Lock()
        sous._commandes = None
        return sous

    # ── commandes ──────────────────────────────────────────────────────

    def commencer(self):
        """Ouvre le relevé des commandes d'une nouvelle vérification."""
        self._commandes = OrderedDict()
        self._depots_notes = False

    def commandes(self):
        """Les commandes notées, « (×N) » quand une forme s'est répétée."""
        return [
            texte if n == 1 else f"{texte}   (×{n})"
            for texte, n in (self._commandes or {}).items()
        ]

    def noter(self, texte):
        tampon = getattr(self._fil, "tampon", None)
        if tampon is not None:
            tampon.append(texte)
            return
        if self._commandes is None:
            return
        with self._verrou:
            self._commandes[texte] = self._commandes.get(texte, 0) + 1

    def en_parallele(self, fonction, elements, max_workers=8):
        """[fonction(élément)] dans l'ordre des `elements`, calculés en
        parallèle. Les commandes que chaque appel note sont tamponnées dans
        son fil, puis versées au relevé dans l'ordre des éléments : le
        rapport ne dépend pas de l'appel qui finit le premier."""

        def appeler(element):
            self._fil.tampon = []
            try:
                return fonction(element), self._fil.tampon
            finally:
                self._fil.tampon = None

        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            paires = list(pool.map(appeler, elements))
        for _rendu, notees in paires:
            for texte in notees:
                self.noter(texte)
        return [rendu for rendu, _notees in paires]

    def lancer(self, args, cwd=None, forme=None, delai=DELAI_GIT, env=None):
        """Lance `args` et note la commande ; ne lève jamais.

        `forme` remplace le texte noté : un appel répété sur chaque dépôt se
        note une fois, avec « <dépôt> » à la place du chemin. Rend le
        CompletedProcess, avec le code 127 si le programme manque et 124 si
        le délai expire.
        """
        if forme is None:
            forme = shlex.join(args)
            if cwd and os.path.abspath(cwd) != self.racine:
                forme = f"cd {shlex.quote(self.relatif(cwd))} && {forme}"
        self.noter(forme)
        try:
            return subprocess.run(
                args,
                cwd=cwd or self.racine,
                capture_output=True,
                text=True,
                timeout=delai,
                env=env,
            )
        except subprocess.TimeoutExpired:
            return subprocess.CompletedProcess(args, 124, "", "timeout")
        except OSError as exc:
            return subprocess.CompletedProcess(args, 127, "", str(exc))

    @staticmethod
    def afficher(args):
        """Une commande lisible : les marqueurs « <…> » restent nus."""
        return re.sub(r"'(<[^'>]*>)'", r"\1", shlex.join(args))

    def relatif(self, chemin):
        rel = os.path.relpath(os.path.abspath(chemin), self.racine)
        return "." if rel == "." else rel

    # ── dépôts ─────────────────────────────────────────────────────────

    def depots(self):
        """[(chemin relatif, attributs du manifeste ou None)] à examiner.

        ERPLibre (« . ») d'abord ; avec la portée « tous », chaque projet du
        manifeste local dont le clone existe, dans l'ordre du manifeste.
        """
        caches = self._caches
        if self.portee_depots == DEPOTS_TOUS:
            from script.git import repo_state

            # Une fois par vérification, qu'elle lise ou trouve en cache ;
            # sous verrou, ses fils parallèles ne la notent pas deux fois.
            with caches.verrou:
                premiere = not self._depots_notes
                self._depots_notes = True
            if premiere:
                self.noter(f"cat {repo_state.MANIFESTE_LOCAL}")
        with caches.verrou:
            if caches.depots is None:
                caches.depots = self._lire_depots()
            return caches.depots

    def _lire_depots(self):
        depots = [(".", None)]
        if self.portee_depots == DEPOTS_TOUS:
            from script.git import repo_state

            try:
                local = repo_state.lire_manifeste_local(self.racine)
            except Exception:
                local = None
            if local:
                remotes, defaut, projets = local
                for attrs in projets:
                    complet = dict(attrs)
                    for cle in ("remote", "revision"):
                        if cle in defaut:
                            complet.setdefault(cle, defaut[cle])
                    chemin = repo_state.chemin_projet(complet)
                    if os.path.exists(
                        os.path.join(self.racine, chemin, ".git")
                    ):
                        depots.append((chemin, complet))
        return depots

    def plusieurs_depots(self):
        return len(self.depots()) > 1

    def git(self, depot, *args, delai=DELAI_GIT, forme=None):
        """`git -C <dépôt> args`, noté une fois par forme sur plusieurs
        dépôts. `forme` remplace les arguments notés quand l'un d'eux varie
        d'un dépôt à l'autre."""
        cmd = ["git", "-C", depot, *args]
        return self.lancer(
            cmd, forme=self._forme_git(depot, args, forme), delai=delai
        )

    def _forme_git(self, depot, args, forme=None):
        """Le texte noté pour `git -C depot args` (voir `git`)."""
        if forme is not None:
            return f"git -C {self.depot_note(depot)} {forme}"
        if self.marqueur(depot):
            return self.afficher(["git", "-C", "<dépôt>", *args])
        return shlex.join(["git", "-C", depot, *args])

    def marqueur(self, depot):
        """Le chemin d'un dépôt d'addons s'affiche « <dépôt> » quand
        plusieurs dépôts passent : leurs commandes se notent alors une seule
        fois. ERPLibre garde son chemin, « . »."""
        return depot != "." and self.plusieurs_depots()

    def depot_note(self, depot):
        return "<dépôt>" if self.marqueur(depot) else shlex.quote(depot)

    def chaque_depot(self, fonction):
        """[(dépôt, fonction(dépôt, attributs))] dans l'ordre des dépôts,
        calculés en parallèle : chaque appel à git attend surtout le
        disque."""
        depots = self.depots()
        rendus = self.en_parallele(lambda d: fonction(*d), depots)
        return [(d[0], r) for d, r in zip(depots, rendus)]

    def status(self, depot):
        """Les lignes de `git status --porcelain=v2`, en cache par dépôt."""
        args = ("status", "--porcelain=v2", "--untracked-files=normal")
        caches = self._caches
        with caches.verrou:
            if depot in caches.status:
                self.noter(self._forme_git(depot, args))
                return caches.status[depot]
        sortie = self.git(depot, *args)
        lignes = (
            None
            if sortie.returncode
            else [ligne for ligne in sortie.stdout.splitlines() if ligne]
        )
        with caches.verrou:
            return caches.status.setdefault(depot, lignes)

    # ── fichiers ───────────────────────────────────────────────────────

    def base_de(self, depot, attrs):
        """La ref de base d'un dépôt pour la portée « depuis la base »."""
        if attrs is None:
            return BRANCHE_BASE_ERPLIBRE
        from script.git import repo_state

        return repo_state.ref_cible(attrs)

    def fichiers(self, depot, attrs):
        """(fichiers relatifs au dépôt, raison si la liste manque).

        Les fichiers effacés n'en font pas partie : il n'y a rien à
        vérifier dans un fichier qui n'existe plus.
        """
        if self.portee_fichiers == FICHIERS_TOUS:
            sortie = self.git(depot, "ls-files")
            if sortie.returncode:
                return None, sortie.stderr.strip()
            noms = sortie.stdout.splitlines()
        else:
            if self.portee_fichiers == FICHIERS_DEPUIS_BASE:
                base = self.base_de(depot, attrs)
                if not base:
                    return None, t("no base branch")
                sortie = self.git(
                    depot,
                    "merge-base",
                    base,
                    "HEAD",
                    forme=(
                        "merge-base <base> HEAD"
                        if self.marqueur(depot)
                        else f"merge-base {shlex.quote(base)} HEAD"
                    ),
                )
                if sortie.returncode:
                    return None, f"{t('base not found:')} {base}"
                reference = sortie.stdout.strip()
                if self.marqueur(depot):
                    reference_affichee = "<base>"
                else:
                    reference_affichee = reference[:12]
            else:
                reference = reference_affichee = "HEAD"
            cmd = ["diff", "--name-only", "--diff-filter=d", reference]
            forme = self.afficher(
                [
                    "git",
                    "-C",
                    "<dépôt>" if self.marqueur(depot) else depot,
                    "diff",
                    "--name-only",
                    "--diff-filter=d",
                    reference_affichee,
                ]
            )
            sortie = self.lancer(["git", "-C", depot, *cmd], forme=forme)
            if sortie.returncode:
                return None, sortie.stderr.strip()
            noms = sortie.stdout.splitlines()
            nouveaux = self.git(
                depot, "ls-files", "--others", "--exclude-standard"
            )
            noms += nouveaux.stdout.splitlines()
        absolu = os.path.join(self.racine, depot)
        vus, rendus = set(), []
        for nom in noms:
            if (
                nom
                and nom not in vus
                and os.path.isfile(os.path.join(absolu, nom))
            ):
                vus.add(nom)
                rendus.append(nom)
        return rendus, None

    def snapshot(self):
        """(données, stderr) de `repo_state.py snapshot`, lu une fois par
        contexte : le manifeste et les branches des dépôts le partagent.
        `données` vaut None quand la sortie n'est pas du JSON."""
        python = self.outil("python3") or "python3"
        script = os.path.join("script", "git", "repo_state.py")
        forme = f"{self.relatif(python)} {script} snapshot"
        caches = self._caches
        with caches.verrou:
            if caches.snapshot is not None:
                self.noter(forme)
                return caches.snapshot
            sortie = self.lancer(
                [python, script, "snapshot"], forme=forme, delai=DELAI_OUTIL
            )
            try:
                donnees = json.loads(sortie.stdout)
            except ValueError:
                donnees = None
            caches.snapshot = (donnees, sortie.stderr)
            return caches.snapshot

    def outil(self, nom):
        """Le chemin d'un outil du venv d'ERPLibre, ou du PATH, ou None."""
        chemin = os.path.join(self.racine, VENV_ERPLIBRE, "bin", nom)
        if os.access(chemin, os.X_OK):
            return chemin
        return shutil.which(nom)


def chemin_status(ligne):
    """(marque XY, chemin) d'une ligne de `git status --porcelain=v2`.

    Le chemin est le dernier champ et peut contenir des espaces : le nombre
    de champs qui le précèdent dépend du type de ligne. Un renommage porte
    « nouveau<TAB>ancien » ; seul le nouveau chemin est rendu.
    """
    if ligne.startswith("? ") or ligne.startswith("! "):
        return ligne[0] * 2, ligne[2:]
    champs = {"1": 8, "2": 9, "u": 10}.get(ligne[:1])
    if champs is None:
        return "", ligne
    chemin = ligne.split(" ", champs)[-1]
    return ligne[2:4], chemin.split("\t")[0]


def _limiter(lignes):
    if len(lignes) <= MAX_DETAILS:
        return lignes
    reste = len(lignes) - MAX_DETAILS
    return lignes[:MAX_DETAILS] + [f"… {reste} {t('more')}"]


def _nom_depot(depot):
    return "ERPLibre" if depot == "." else depot


def _decompte_depots(ctx):
    n = len(ctx.depots())
    return f"{n} {t('repository') if n == 1 else t('repositories')}"


# ── Code ────────────────────────────────────────────────────────────────


def verifier_conflits(ctx):
    """Une fusion, un rebase, un cherry-pick ou un revert interrompu, ou
    des fichiers encore en conflit, dans un des dépôts."""

    def examiner(depot, _attrs):
        sortie = ctx.git(depot, "rev-parse", "--absolute-git-dir")
        if sortie.returncode:
            return None
        dossier = sortie.stdout.strip()
        operations = [
            nom
            for trace, nom in OPERATIONS_GIT
            if os.path.exists(os.path.join(dossier, trace))
        ]
        lignes = ctx.status(depot) or []
        conflits = [
            chemin_status(ligne)[1] for ligne in lignes if ligne[:2] == "u "
        ]
        return sorted(set(operations)), conflits

    rendus = ctx.chaque_depot(examiner)
    # Noté après coup : l'ordre affiché suit celui de l'examen.
    ctx.noter(
        "ls <git-dir>/{" + ",".join(trace for trace, _ in OPERATIONS_GIT) + "}"
    )
    details = []
    for depot, rendu in rendus:
        if rendu is None:
            details.append(f"{_nom_depot(depot)} : {t('unreadable by git')}")
            continue
        operations, conflits = rendu
        if operations or conflits:
            texte = ", ".join(operations) or t("conflicted files")
            details.append(
                f"{_nom_depot(depot)} : {texte}"
                + (
                    f" — {len(conflits)} {t('conflicted files')}"
                    if conflits
                    else ""
                )
            )
            details += [f"   {c}" for c in conflits[:5]]
    if details:
        return Resultat(
            titre(verifier_conflits),
            ECHEC,
            f"{len([d for d in details if not d.startswith('   ')])}"
            f" / {_decompte_depots(ctx)}",
            _limiter(details),
        )
    return Resultat(
        titre(verifier_conflits),
        OK,
        f"{t('none')} ({_decompte_depots(ctx)})",
    )


def verifier_non_commites(ctx):
    """Les fichiers modifiés, indexés ou non suivis de chaque dépôt."""

    def examiner(depot, _attrs):
        return ctx.status(depot)

    details, sales = [], 0
    for depot, lignes in ctx.chaque_depot(examiner):
        if lignes is None:
            details.append(f"{_nom_depot(depot)} : {t('unreadable by git')}")
            continue
        if not lignes:
            continue
        sales += 1
        details.append(f"{_nom_depot(depot)} : {len(lignes)} {t('files')}")
        if not ctx.plusieurs_depots() or len(lignes) <= 5:
            for ligne in lignes[:10]:
                marque, chemin = chemin_status(ligne)
                details.append(f"   {marque} {chemin}")
    if not details:
        return Resultat(
            titre(verifier_non_commites),
            OK,
            f"{t('none')} ({_decompte_depots(ctx)})",
        )
    return Resultat(
        titre(verifier_non_commites),
        ALERTE,
        f"{sales} / {_decompte_depots(ctx)}",
        _limiter(details),
    )


def verifier_non_pousses(ctx):
    """Les branches locales qui portent des commits qu'aucune branche
    distante connue n'a.

    La comparaison se fait contre les refs distantes que le clone connaît
    déjà, sans « git fetch » : un push fait d'ailleurs ne se voit qu'après
    la prochaine récupération.
    """

    def examiner(depot, _attrs):
        sortie = ctx.git(
            depot,
            "for-each-ref",
            "refs/heads",
            "--format=%(refname:short)%09%(upstream:short)",
        )
        if sortie.returncode:
            return None
        branches = []
        for ligne in sortie.stdout.splitlines():
            nom, _, amont = ligne.partition("\t")
            compte = ctx.git(
                depot,
                "rev-list",
                "--count",
                nom,
                "--not",
                "--remotes",
                forme="rev-list --count <branche> --not --remotes",
            )
            try:
                n = int(compte.stdout.strip() or 0)
            except ValueError:
                n = 0
            if n:
                branches.append((nom, n, amont))
        return branches

    details, total = [], 0
    for depot, branches in ctx.chaque_depot(examiner):
        if branches is None:
            details.append(f"{_nom_depot(depot)} : {t('unreadable by git')}")
            continue
        for nom, n, amont in branches:
            total += 1
            sans = "" if amont else f" — {t('no upstream')}"
            details.append(
                f"{_nom_depot(depot)} : {nom} +{n} {t('commits')}{sans}"
            )
    note = t("compared with the known remote refs, without git fetch")
    if not total:
        return Resultat(
            titre(verifier_non_pousses),
            OK,
            f"{t('none')} ({_decompte_depots(ctx)})",
            [note],
        )
    return Resultat(
        titre(verifier_non_pousses),
        ALERTE,
        f"{total} {t('branches')}",
        _limiter(details) + [note],
    )


def _par_lots(liste):
    for i in range(0, len(liste), LOT_FICHIERS):
        yield liste[i : i + LOT_FICHIERS]


RE_MODULE_ODOO = re.compile(r"^(?:addons|odoo[^/]*/addons)/")
# Les vérifications de formatage, par contexte, comme les applique
# script/maintenance/format_python.sh : (outil, arguments, analyse de la
# sortie). Les modules Odoo suivent isort + black ciblant py37, l'outillage
# suit ruff réglé par .ruff.toml.
FORMATEURS = {
    "odoo": (
        ("isort", ["--profile", "black", "-l", "79", "--check-only"]),
        ("black", ["-l", "79", "--preview", "-t", "py37", "--check"]),
    ),
    "outillage": (
        ("ruff", ["check", "--select", "I", "--force-exclude", "--quiet"]),
        ("ruff", ["format", "--check", "--force-exclude", "--quiet"]),
    ),
}


def fichiers_fautifs(outil, sortie, racine):
    """Les fichiers qu'un formateur en mode vérification déclare à
    reprendre, relatifs à la racine."""
    texte = sortie.stdout + "\n" + sortie.stderr
    fautifs = []
    for ligne in texte.splitlines():
        chemin = None
        if outil == "black" and ligne.startswith("would reformat "):
            chemin = ligne[len("would reformat ") :]
        elif outil == "black" and ligne.startswith("error: cannot format "):
            chemin = ligne[len("error: cannot format ") :].split(":")[0]
        elif outil == "isort" and ligne.startswith("ERROR: "):
            chemin = ligne[len("ERROR: ") :].split(" Imports are")[0]
        elif outil == "ruff" and ligne.startswith("Would reformat: "):
            chemin = ligne[len("Would reformat: ") :]
        elif outil == "ruff" and ":" in ligne and " I001" in ligne:
            chemin = ligne.split(":")[0]
        if chemin:
            if os.path.isabs(chemin):
                chemin = os.path.relpath(chemin, racine)
            fautifs.append(chemin)
    return fautifs


def verifier_formatage(ctx):
    """Le formatage Python de la portée, vérifié sans rien écrire, par les
    outils et les réglages de `make format` (voir FORMATEURS).

    Les fichiers XML, JS, CSS et shell, que `make format` passe à prettier
    et à shfmt, ne sont pas vérifiés.
    """
    par_contexte = {"odoo": [], "outillage": []}
    manques = []
    # Deux commandes git par dépôt : en parallèle, dans l'ordre des dépôts.
    for depot, (fichiers, raison) in ctx.chaque_depot(ctx.fichiers):
        if fichiers is None:
            manques.append(f"{_nom_depot(depot)} : {raison}")
            continue
        for fichier in fichiers:
            if not fichier.endswith(".py"):
                continue
            chemin = os.path.normpath(os.path.join(depot, fichier))
            contexte = "odoo" if RE_MODULE_ODOO.match(chemin) else "outillage"
            par_contexte[contexte].append(chemin)
    examines = sum(len(f) for f in par_contexte.values())
    note = t("XML, JS, CSS and shell files are not checked")
    if not examines:
        if manques:
            return Resultat(
                titre(verifier_formatage),
                ALERTE,
                t("no Python file in scope"),
                manques,
            )
        return Resultat(
            titre(verifier_formatage), OK, t("no Python file in scope"), [note]
        )
    fautifs, absents = {}, set()
    for contexte, fichiers in par_contexte.items():
        if not fichiers:
            continue
        for outil, options in FORMATEURS[contexte]:
            binaire = ctx.outil(outil)
            if not binaire:
                absents.add(outil)
                continue
            forme = shlex.join([ctx.relatif(binaire), *options])
            for lot in _par_lots(fichiers):
                sortie = ctx.lancer(
                    [binaire, *options, *lot],
                    forme=f"{forme} <{len(fichiers)} {t('Python files')}>",
                    delai=DELAI_OUTIL,
                )
                for chemin in fichiers_fautifs(outil, sortie, ctx.racine):
                    fautifs.setdefault(chemin, set()).add(outil)
    details = [
        f"{', '.join(sorted(outils))} : {chemin}"
        for chemin, outils in sorted(fautifs.items())
    ]
    details = _limiter(details) + manques
    if absents:
        details.append(f"{t('missing tools:')} {', '.join(sorted(absents))}")
    details.append(note)
    if fautifs:
        details.insert(len(details) - 1, t("Fix: make format"))
        return Resultat(
            titre(verifier_formatage),
            ALERTE,
            f"{len(fautifs)} / {examines} {t('files to reformat')}",
            details,
        )
    return Resultat(
        titre(verifier_formatage),
        ALERTE if manques or absents else OK,
        f"{examines} {t('files checked')}",
        details,
    )


def verifier_hygiene(ctx):
    """`check_comment_hygiene.py` sur les fichiers d'ERPLibre de la portée.

    Les dépôts d'addons n'en font pas partie : la règle est celle
    d'ERPLibre, pas celle des projets amont dont viennent ces dépôts.
    """
    nom = titre(verifier_hygiene)
    fichiers, raison = ctx.fichiers(".", None)
    if fichiers is None:
        return Resultat(nom, SAUTE, raison)
    if not fichiers:
        return Resultat(nom, OK, t("no file in scope"))
    script = os.path.join("script", "analyse", "check_comment_hygiene.py")
    python = ctx.outil("python3") or "python3"
    sortie = ctx.lancer(
        [python, script, "--json", "--no-color", *fichiers],
        forme=f"{ctx.relatif(python)} {script} --json --no-color"
        f" <{len(fichiers)} {t('files')}>",
        delai=DELAI_OUTIL,
    )
    try:
        donnees = json.loads(sortie.stdout)
    except ValueError:
        return Resultat(
            nom,
            ECHEC,
            t("unreadable output"),
            _limiter(sortie.stderr.strip().splitlines()),
        )
    trouvailles = donnees.get("findings") or []
    if not trouvailles:
        return Resultat(
            nom, OK, f"{donnees.get('scanned', 0)} {t('files checked')}"
        )
    identifiants = [f for f in trouvailles if f.get("kind") == "identifiant"]
    details = [
        f"{'🔴' if f.get('kind') == 'identifiant' else '🟡'}"
        f" {ctx.relatif(f.get('file', ''))}:{f.get('line')}"
        f" {f.get('kind')} « {f.get('excerpt')} »"
        for f in trouvailles
    ]
    return Resultat(
        nom,
        ECHEC if identifiants else ALERTE,
        f"{len(identifiants)} 🔴 · {len(trouvailles) - len(identifiants)} 🟡",
        _limiter(details),
    )


def _generes(base):
    """Les fichiers que mmg tire de « X.base.md » : « X.md », « X.fr.md »."""
    racine = base[: -len(".base.md")]
    return [f"{racine}.md", f"{racine}.fr.md"]


def verifier_docs(ctx):
    """Les « .md » et « .fr.md » qui ne suivent plus leur « .base.md ».

    mmg régénère une copie des sources dans un dossier temporaire ; le
    checkout n'est pas touché. Dans la portée des fichiers modifiés, une
    source compte dès qu'elle ou l'un de ses fichiers générés a changé.
    """
    nom = titre(verifier_docs)
    mmg = ctx.outil("mmg")
    if not mmg:
        return Resultat(nom, SAUTE, t("mmg is missing"))
    fichiers, raison = ctx.fichiers(".", None)
    if fichiers is None:
        return Resultat(nom, SAUTE, raison)
    bases = set()
    for fichier in fichiers:
        if fichier.endswith(".base.md"):
            bases.add(fichier)
        elif fichier.endswith(".md"):
            souche = (
                fichier[: -len(".fr.md")]
                if fichier.endswith(".fr.md")
                else fichier[:-3]
            )
            candidat = f"{souche}.base.md"
            if os.path.isfile(os.path.join(ctx.racine, candidat)):
                bases.add(candidat)
    bases = sorted(bases)
    if not bases:
        return Resultat(nom, OK, t("no doc in scope"))
    with tempfile.TemporaryDirectory(prefix="healthcheck_mmg_") as tmp:
        for base in bases:
            cible = os.path.join(tmp, base)
            os.makedirs(os.path.dirname(cible), exist_ok=True)
            shutil.copyfile(os.path.join(ctx.racine, base), cible)
        ctx.noter(f"cp <{len(bases)} .base.md> <tmp>/")
        sortie = ctx.lancer(
            [mmg, "--yes", *bases],
            cwd=tmp,
            forme=f"cd <tmp> && {ctx.relatif(mmg)} --yes"
            f" <{len(bases)} .base.md>",
            delai=DELAI_OUTIL,
        )
        if sortie.returncode:
            return Resultat(
                nom,
                ECHEC,
                t("mmg failed"),
                _limiter((sortie.stdout + sortie.stderr).strip().splitlines()),
            )
        ctx.noter(f"cmp <tmp>/X.md X.md   (×{2 * len(bases)})")
        ecarts = []
        for base in bases:
            for genere in _generes(base):
                neuf = os.path.join(tmp, genere)
                if not os.path.isfile(neuf):
                    continue
                actuel = os.path.join(ctx.racine, genere)
                try:
                    with open(neuf, "rb") as a, open(actuel, "rb") as b:
                        pareil = a.read() == b.read()
                except OSError:
                    pareil = False
                if not pareil:
                    ecarts.append(genere)
    if ecarts:
        return Resultat(
            nom,
            ALERTE,
            f"{len(ecarts)} {t('files to regenerate')} — make doc_markdown",
            _limiter(ecarts),
        )
    return Resultat(nom, OK, f"{len(bases)} {t('docs up to date')}")


# Le libellé, clé de traduction, de chaque « freeze.alignment » de
# `repo_state` qui n'est pas « conforme ».
ECARTS_GEL = {
    "en_avance": "ahead of the freeze",
    "en_retard": "behind the freeze",
    "decale": "diverged from the freeze",
    "introuvable": "frozen commit missing from the clone",
    "indetermine": "shallow clone, gap to the freeze unknown",
    "erreur": "git could not measure the gap to the freeze",
}
# Les états de `repo_state` que « Addons face au manifeste » détaille : tout
# écart à la cible du manifeste local, en avance compris — des commits que la
# branche du manifeste n'a pas encore.
ETATS_SIGNALES = ("decale", "en_avance", "absent", "erreur")


def _ecart_gel(depot):
    """La ligne de détail d'un dépôt dont HEAD n'est pas le commit gelé
    (« freeze » de `repo_state`), ou None s'il l'est, n'a pas de gel, ou si
    sa ligne d'état dit déjà le même écart : un dépôt signalé dont la cible
    du manifeste local EST le commit gelé."""
    gel = depot.get("freeze") or {}
    alignement = gel.get("alignment")
    if alignement in (None, "conforme"):
        return None
    if (
        depot.get("state") in ETATS_SIGNALES
        and depot.get("target")
        and depot.get("target") == depot.get("freeze_revision")
    ):
        return None
    head = (depot.get("head") or "")[:10]
    commit = (depot.get("freeze_revision") or "")[:10]
    libelle = ECARTS_GEL.get(alignement, alignement)
    ligne = (
        f"{t(libelle)} : {depot.get('path')} — "
        f"HEAD {head}, {t('freeze')} {commit}"
    )
    if gel.get("ahead") is not None:
        ligne += f" (+{gel['ahead']} −{gel['behind']})"
    return ligne


def verifier_manifeste(ctx):
    """L'écart de chaque dépôt d'addons à ce que le manifeste local demande,
    et de son HEAD au « freeze-revision » de `manifest/`, lus par
    `repo_state.py snapshot`.

    Le manifeste local suit une branche hors d'un checkout gelé : un dépôt
    peut y être conforme et rester loin de son gel, que seul « freeze »
    voit."""
    nom = titre(verifier_manifeste)
    donnees, erreur = ctx.snapshot()
    if donnees is None:
        return Resultat(
            nom,
            ECHEC,
            t("unreadable output"),
            _limiter(erreur.strip().splitlines()),
        )
    depots = donnees.get("repos") or []
    if not donnees.get("local_manifest") and not depots:
        return Resultat(nom, SAUTE, t("no local manifest"))
    comptes = {}
    details = []
    hors_gel = []
    perimes = manifeste_perime(donnees)
    for depot in depots:
        if depot in perimes:
            continue
        etat = depot.get("state")
        comptes[etat] = comptes.get(etat, 0) + 1
        if etat in ETATS_SIGNALES:
            ligne = f"{etat} : {depot.get('path')}"
            if depot.get("ahead") is not None:
                ligne += f" (+{depot['ahead']} −{depot['behind']})"
            if depot.get("error"):
                ligne += f" — {depot['error']}"
            details.append(ligne)
        ligne = _ecart_gel(depot)
        if ligne:
            hors_gel.append(ligne)
    resume = " · ".join(f"{n} {etat}" for etat, n in sorted(comptes.items()))
    if perimes:
        resume += f" · {len(perimes)} {t('stale local manifest')}"
        details += [
            f"{t('stale local manifest')} : {d.get('path')} —"
            f" {t('local target')} {d['revision'][:10]},"
            f" {t('freeze')} {d['freeze_revision'][:10]}"
            for d in perimes
        ]
    if hors_gel:
        resume += f" · {len(hors_gel)} {t('off the freeze')}"
        details += hors_gel
    resolutions = resolutions_gel(ctx, depots)
    if perimes:
        resolutions.insert(
            0,
            Resolution(
                REGENERER,
                f"🧾 {t('Regenerate the local manifest')}"
                f" ({COMMANDE_REGENERER})",
                [
                    t(
                        "In a frozen checkout, the local manifest still targets an older freeze than manifest/: it was generated before the last freeze. It is written again from manifest/, then repo sync puts each repository on its freeze; a repository with modified files makes the sync fail without being overwritten."
                    )
                ]
                + [f"   {d.get('path')}" for d in perimes],
                perimes,
            ),
        )
    if details:
        return Resultat(
            nom, ALERTE, resume, _limiter(details), resolutions=resolutions
        )
    return Resultat(nom, OK, resume, resolutions=resolutions)


REGENERER = "regenerer"
COMMANDE_REGENERER = "make repo_configure_all FREEZE=1"


def manifeste_perime(donnees):
    """Les dépôts dont le manifeste local, en checkout gelé, vise un autre
    commit que le « freeze-revision » de `manifest/` : le manifeste local a
    été généré avant le dernier gel. Leur écart à sa cible (« en_avance »,
    « decale ») ne dit alors rien de vrai, et la réponse est de le
    régénérer. Hors d'un checkout gelé, la cible est une branche : rien
    n'est périmé de cette façon."""
    from script.git import manifest_freeze

    if donnees.get("mode") != "frozen":
        return []
    return [
        d
        for d in donnees.get("repos") or []
        if d.get("freeze_revision")
        and manifest_freeze.is_sha((d.get("revision") or "").lower())
        and d["revision"].lower() != d["freeze_revision"].lower()
    ]


def _ligne_gel(depot):
    alignement = freeze_resolution.hors_gel(depot)
    return f"   {depot['path']} — {t(ECARTS_GEL.get(alignement, alignement))}"


def resolutions_gel(ctx, depots):
    """Les résolutions des dépôts hors de leur gel, classés par
    `freeze_resolution.classer`. Un `git status` par dépôt hors du gel, et
    pour eux seuls, dit lesquels ont des fichiers modifiés."""
    candidats = [d for d in depots if freeze_resolution.hors_gel(d)]
    if not candidats:
        return []

    def est_sale(depot):
        fait = ctx.lancer(
            ["git", "-C", depot["path"], "status", "--porcelain"],
            forme="git -C <dépôt> status --porcelain",
        )
        return fait.returncode != 0 or bool(fait.stdout.strip())

    classes = freeze_resolution.classer(candidats, est_sale)
    resolutions = []
    remettre = classes[freeze_resolution.REMETTRE]
    if remettre:
        resolutions.append(
            Resolution(
                freeze_resolution.REMETTRE,
                f"🧊 {t('Put back on the freeze:')} {len(remettre)}"
                f" {t('repositories')}",
                [
                    t(
                        "Behind their freeze, or missing the frozen commit: HEAD is detached on the frozen commit, fetched first from the manifest URL when the clone lacks it."
                    )
                ]
                + [_ligne_gel(d) for d in remettre],
                remettre,
            )
        )
    maj = classes[freeze_resolution.MAJ_GEL]
    if maj:
        resolutions.append(
            Resolution(
                freeze_resolution.MAJ_GEL,
                f"🧊 {t('Update the freeze to HEAD:')} {len(maj)}"
                f" {t('repositories')}",
                [
                    t(
                        "HEAD carries commits the freeze lacks: the freeze in manifest/ moves to HEAD, for each HEAD already pushed; the others are named with the push to make first."
                    )
                ]
                + [_ligne_gel(d) for d in maj],
                maj,
            )
        )
    if classes[freeze_resolution.SALES]:
        resolutions.append(
            Resolution(
                None,
                "",
                [
                    t(
                        "Skipped, modified files: commit or stash them, then run the check again."
                    )
                ]
                + [_ligne_gel(d) for d in classes[freeze_resolution.SALES]],
            )
        )
    if classes[freeze_resolution.MANUELS]:
        resolutions.append(
            Resolution(
                None,
                "",
                [
                    t(
                        "To settle by hand: HEAD and the freeze both carry commits, or the shallow clone hides the gap. Compare with:"
                    )
                ]
                + [
                    f"   git -C {d['path']} log --oneline --left-right"
                    f" HEAD...{(d.get('freeze_revision') or '')[:10]}"
                    for d in classes[freeze_resolution.MANUELS]
                ],
            )
        )
    return resolutions


def verifier_branches(ctx):
    """Les branches locales des dépôts d'addons dont la pointe n'est pas
    HEAD. git-repo laisse HEAD détaché : une branche ouverte par
    « repo start », ou un travail commité sur une branche puis quitté par
    une synchronisation, reste en dehors de ce que le checkout exécute.
    Une branche qui porte des commits absents de HEAD est signalée ; une
    branche seulement en retard sur HEAD est une information."""
    nom = titre(verifier_branches)
    donnees, erreur = ctx.snapshot()
    if donnees is None:
        return Resultat(
            nom,
            ECHEC,
            t("unreadable output"),
            _limiter(erreur.strip().splitlines()),
        )
    depots = [d for d in donnees.get("repos") or [] if d.get("head")]
    if not depots:
        return Resultat(nom, SAUTE, t("no local manifest"))

    def examiner(depot):
        refs = ctx.lancer(
            [
                "git",
                "-C",
                depot["path"],
                "for-each-ref",
                "--format=%(refname:short) %(objectname)",
                "refs/heads",
            ],
            forme="git -C <dépôt> for-each-ref refs/heads",
        )
        ecarts = []
        for ligne in refs.stdout.splitlines():
            branche, _, sha = ligne.rpartition(" ")
            if not sha or sha == depot["head"]:
                continue
            compte = ctx.lancer(
                [
                    "git",
                    "-C",
                    depot["path"],
                    "rev-list",
                    "--left-right",
                    "--count",
                    f"HEAD...{sha}",
                ],
                forme=(
                    "git -C <dépôt> rev-list --left-right --count"
                    " HEAD...<branche>"
                ),
            )
            try:
                seul_head, seul_branche = map(int, compte.stdout.split())
            except ValueError:
                seul_head = seul_branche = None
            ecarts.append((branche, seul_branche, seul_head))
        return ecarts

    rendus = ctx.en_parallele(examiner, depots)
    avec_travail, en_retard = [], []
    for depot, ecarts in zip(depots, rendus):
        for branche, plus, moins in ecarts:
            if plus is None:
                avec_travail.append(f"{depot['path']} : {branche}")
            elif plus:
                avec_travail.append(
                    f"{depot['path']} : {branche} (+{plus} −{moins})"
                )
            else:
                en_retard.append(f"{depot['path']} : {branche} (+0 −{moins})")
    if not avec_travail and not en_retard:
        return Resultat(
            nom,
            OK,
            f"{len(depots)} {t('repositories')},"
            f" {t('no local branch off HEAD')}",
        )
    morceaux = []
    if avec_travail:
        morceaux.append(f"{len(avec_travail)} {t('with commits HEAD lacks')}")
    if en_retard:
        morceaux.append(f"{len(en_retard)} {t('behind HEAD')}")
    return Resultat(
        nom,
        ALERTE if avec_travail else INFO,
        " · ".join(morceaux),
        _limiter(avec_travail + en_retard),
    )


def verifier_hooks(ctx):
    nom = titre(verifier_hooks)
    ctx.noter("git -C . config --get core.hooksPath")
    ctx.noter(
        "test -x "
        + os.path.join(
            todo_etat.CHEMIN_HOOKS_GIT,
            "{" + ",".join(todo_etat.HOOKS_GIT) + "}",
        )
    )
    ligne = todo_etat.ligne_hooks_git(ctx.racine)
    if not ligne:
        return Resultat(nom, SAUTE, t("not a git checkout"))
    icone, _, texte = ligne.partition(" ")
    if icone == todo_etat.OK:
        return Resultat(nom, OK, texte.strip())
    return Resultat(
        nom,
        ALERTE,
        texte.strip(),
        resolutions=[
            Resolution(
                HOOKS_GIT,
                f"🪝 {t('Install the git hooks')}",
                [
                    t(
                        "core.hooksPath points at script/git/hooks and each hook gets its execution bit, as Execute › Git repository › Settings does."
                    )
                ],
            )
        ],
    )


HOOKS_GIT = "hooks_git"


# ── Environnement ───────────────────────────────────────────────────────


def verifier_venv(ctx):
    """Le venv d'Odoo de la version active, et la version de son Python."""
    nom = titre(verifier_venv)
    cle = todo_etat._lire(os.path.join(ctx.racine, ".erplibre-version"))
    attendu = todo_etat._lire(os.path.join(ctx.racine, ".python-odoo-version"))
    if not cle:
        return Resultat(nom, SAUTE, t("no .erplibre-version"))
    venv = f".venv.{cle}"
    python = os.path.join(venv, "bin", "python")
    sortie = ctx.lancer(
        [os.path.join(ctx.racine, python), "--version"],
        forme=f"{python} --version",
    )
    if sortie.returncode:
        return Resultat(nom, ECHEC, f"{venv} {t('missing or broken')}")
    obtenu = (sortie.stdout or sortie.stderr).strip()
    if attendu and obtenu != f"Python {attendu}":
        return Resultat(
            nom, ALERTE, f"{venv} : {obtenu}, {t('expected')} {attendu}"
        )
    return Resultat(nom, OK, f"{venv} · {obtenu}")


MAJ_VENVS = "maj_venvs"


def cles_du_catalogue(racine):
    """Les clés de version (« odoo18.0_python3.12.16 ») du catalogue
    conf/supported_version_erplibre.json, ou un ensemble vide s'il est
    illisible : rien n'est alors déclaré obsolète."""
    try:
        with open(os.path.join(racine, todo_etat.CATALOGUE)) as fh:
            return set(json.load(fh))
    except (OSError, ValueError):
        return set()


def remplacant(version, cles):
    """La clé du catalogue pour la même version d'Odoo que `version`, ou
    None : « odoo18.0_python3.12.10 » donne « odoo18.0_python3.12.16 »."""
    odoo = version.split("_python", 1)[0]

    def python(cle):
        return tuple(
            int(n) if n.isdigit() else 0
            for n in cle.split("_python", 1)[-1].split(".")
        )

    candidates = [c for c in cles if c.split("_python", 1)[0] == odoo]
    return max(candidates, key=python) if candidates else None


def _ecarts_venv(ctx, choix):
    """L'écart d'un venv (une entrée de `drift.venvs`) à ce qu'il doit
    porter : {"venv", "ecarts": [lignes], "info": [lignes], "erreur"}.
    Un venv d'Odoo passe par la simulation de Poetry, contre le lock de la
    racine pour la version active et contre son propre lock, depuis un
    dossier temporaire, pour une autre ; le venv de l'outillage par
    venv_requirements_drift.py. Rien n'est installé."""
    rendu = {
        "venv": choix["venv"],
        "ecarts": [],
        "info": [],
        "erreur": None,
        "de_trop": [],
        "obsolete": False,
        "remplacant": None,
    }

    def noter_et_lancer(commande, **options):
        ctx.noter(f"{ctx.relatif(commande[0])} {shlex.join(commande[1:])}")
        return subprocess.run(commande, **options)

    if choix["genre"] == "outillage":
        sortie = ctx.lancer(
            [
                os.path.join(choix["venv"], "bin", "python"),
                os.path.join("script", "poetry", "venv_requirements_drift.py"),
                drift.EXIGENCES_OUTILLAGE,
            ],
            forme=(
                f"{choix['venv']}/bin/python"
                " script/poetry/venv_requirements_drift.py"
                f" {drift.EXIGENCES_OUTILLAGE}"
            ),
            delai=DELAI_OUTIL,
        )
        try:
            etat = json.loads(sortie.stdout)
        except ValueError:
            etat = {"erreur": (sortie.stderr or sortie.stdout).strip()}
        if "erreur" in etat:
            rendu["erreur"] = etat["erreur"]
            return rendu
        rendu["ecarts"] += [f"{t('Missing')} {e}" for e in etat["manquantes"]]
        rendu["ecarts"] += [
            f"{t('Out of bounds')} {e['exigence']}"
            f" ({t('installed')} {e['installee']})"
            for e in etat["hors_bornes"]
        ]
        rendu["de_trop"] = [tuple(paire) for paire in etat["de_trop"]]
        if etat["de_trop"]:
            rendu["info"].append(
                f"{len(etat['de_trop'])}"
                f" {t('installed but required by nothing')}"
            )
        return rendu

    version = choix["version"]
    cles = cles_du_catalogue(ctx.racine)
    if cles and version not in cles:
        # Un venv bâti avec un Python que le catalogue ne nomme plus n'a
        # pas de lock : il se remplace, il ne se compare pas.
        rendu["obsolete"] = True
        rendu["remplacant"] = remplacant(version, cles)
        rendu["erreur"] = t("obsolete, not in the catalogue") + (
            f" — {t('Odoo uses')} {rendu['remplacant']}"
            if rendu["remplacant"]
            else ""
        )
        return rendu
    c = drift.chemins(version)
    for fichier in (c["poetry"], c["lock"]):
        if not os.path.isfile(os.path.join(ctx.racine, fichier)):
            rendu["erreur"] = f"{t('missing:')} {fichier}"
            return rendu
    if choix["active"]:
        simulation = drift.simuler(
            ctx.racine, version, executer=noter_et_lancer
        )
    else:
        with drift.projet_temporaire(ctx.racine, version) as projet:
            simulation = drift.simuler(
                ctx.racine, version, executer=noter_et_lancer, projet=projet
            )
    if not simulation["ok"]:
        derniere = (simulation["sortie"].strip().splitlines() or [""])[-1]
        rendu["erreur"] = f"{t('Poetry refuses to compare:')} {derniere}"
        return rendu
    classes = drift.classer(simulation["operations"])
    for action in drift.ECARTS:
        for op in classes.get(action, []):
            versions = (
                op["apres"]
                if action == "Installing"
                else f"{op['avant']} → {op['apres']}"
            )
            rendu["ecarts"].append(f"{op['nom']} {versions}")
    hors_lock = classes.get("Removing", [])
    if hors_lock:
        rendu["info"].append(f"{len(hors_lock)} {t('outside the lock')}")
    return rendu


def verifier_dependances_venvs(ctx):
    """Chaque venv du checkout face à ce qu'il doit porter : un venv
    d'Odoo face à son poetry.lock, le venv de l'outillage face à ses
    exigences. Un venv qui s'en écarte est offert à la résolution « Mettre
    à jour les venvs », qui ne retire rien. Un venv d'Odoo dont la clé n'est
    plus au catalogue est obsolète : sans lock, il est offert au
    remplacement. Un paquet de l'outillage que rien ne demande est offert au
    retrait ; un paquet hors du lock d'un venv d'Odoo reste une
    information."""
    nom = titre(verifier_dependances_venvs)
    active = todo_etat._lire(os.path.join(ctx.racine, ".erplibre-version"))
    candidats = drift.venvs(ctx.racine, active=active)
    if not candidats:
        return Resultat(nom, SAUTE, t("no venv"))
    rendus = ctx.en_parallele(
        lambda c: _ecarts_venv(ctx, c), candidats, max_workers=4
    )
    details, a_jour, obsoletes, de_trop = [], [], [], []
    for choix, rendu in zip(candidats, rendus):
        if rendu["erreur"]:
            details.append(f"{choix['venv']} : ❌ {rendu['erreur']}")
            if rendu["obsolete"]:
                obsoletes.append(dict(choix, remplacant=rendu["remplacant"]))
            continue
        de_trop += [
            {"venv": choix["venv"], "paquet": paquet, "version": numero}
            for paquet, numero in rendu["de_trop"]
        ]
        if rendu["ecarts"]:
            details.append(
                f"{choix['venv']} : {len(rendu['ecarts'])}"
                f" {t('differences')} — {', '.join(rendu['ecarts'][:6])}"
                + (" …" if len(rendu["ecarts"]) > 6 else "")
            )
            choix = dict(choix, resume=details[-1].split(" : ", 1)[1])
            a_jour.append(choix)
        for info in rendu["info"]:
            details.append(f"{choix['venv']} : ℹ️  {info}")
    erreurs = sum(1 for r in rendus if r["erreur"]) - len(obsoletes)
    resume = f"{len(candidats)} venvs"
    if a_jour:
        resume += f" · {len(a_jour)} {t('to update')}"
    if obsoletes:
        resume += f" · {len(obsoletes)} {t('obsolete')}"
    if erreurs:
        resume += f" · {erreurs} {t('unreadable')}"
    resolutions = []
    if a_jour:
        resolutions.append(
            Resolution(
                MAJ_VENVS,
                f"📦 {t('Update the venvs:')} {len(a_jour)}",
                [
                    t(
                        "An Odoo venv gets its lock installed, the active one by the installation, another one from its own lock; the tooling venv gets its missing requirements. A package outside the lock, or required by nothing, stays."
                    )
                ]
                + [f"   {c['venv']} — {c['resume']}" for c in a_jour],
                a_jour,
            )
        )
    if obsoletes:
        resolutions.append(
            Resolution(
                VENVS_OBSOLETES,
                f"🐍 {t('Replace the obsolete Odoo venvs:')} {len(obsoletes)}",
                [
                    t(
                        "A venv built with a Python the catalogue no longer names has no lock. The catalogue's version is installed if its venv is missing, which makes it the active one, then the obsolete venv is deleted, each step on a yes."
                    )
                ]
                + [
                    f"   {c['venv']} → .venv.{c['remplacant']}"
                    if c["remplacant"]
                    else f"   {c['venv']} → {t('no Odoo version left in the catalogue')}"
                    for c in obsoletes
                ],
                obsoletes,
            )
        )
    if de_trop:
        resolutions.append(
            Resolution(
                PAQUETS_DE_TROP,
                f"🧹 {t('Remove the packages nothing requires:')} {len(de_trop)}",
                [
                    t(
                        "Installed in the tooling venv, required by no requirement nor by their dependencies: an installation never removes them. The chosen ones are uninstalled with pip."
                    ),
                    "   "
                    + ", ".join(
                        f"{p['paquet']} {p['version']}" for p in de_trop
                    ),
                ],
                de_trop,
            )
        )
    if a_jour or erreurs or obsoletes:
        statut = ALERTE
    else:
        statut = INFO if de_trop else OK
    return Resultat(nom, statut, resume, details, resolutions=resolutions)


VENVS_OBSOLETES = "venvs_obsoletes"
PAQUETS_DE_TROP = "paquets_de_trop"


def _mettre_a_jour_venvs(venvs, demander, sortie, mettre_a_jour_venv):
    sortie(t("Venvs to update:"))
    choisis = choisir_depots(
        venvs,
        demander,
        sortie,
        decrire=lambda c: f"{c['venv']} — {c['resume']}",
        tous=t("All venvs"),
    )
    if not choisis or mettre_a_jour_venv is None:
        sortie(t("Nothing changed."))
        return False
    for choix in choisis:
        sortie(f"── {choix['venv']} ──")
        mettre_a_jour_venv(choix)
    return True


def verifier_disque(ctx):
    nom = titre(verifier_disque)
    sortie = ctx.lancer(["df", "-Pk", ctx.racine], forme="df -Pk .")
    try:
        champs = sortie.stdout.strip().splitlines()[-1].split()
        libre = int(champs[3]) * 1024
    except (IndexError, ValueError):
        return Resultat(nom, SAUTE, t("unreadable output"))
    texte = f"{libre / 1024**3:.1f} Gio {t('free on')} {champs[-1]}"
    if libre < DISQUE_ECHEC:
        return Resultat(nom, ECHEC, texte)
    if libre < DISQUE_ALERTE:
        return Resultat(nom, ALERTE, texte)
    return Resultat(nom, OK, texte)


def _config_odoo(ctx):
    """{clé: valeur} de config.conf, sans les valeurs « False »."""
    valeurs = {}
    texte = todo_etat._lire(os.path.join(ctx.racine, "config.conf"))
    for ligne in texte.splitlines():
        cle, sep, valeur = ligne.partition("=")
        valeur = valeur.strip()
        if sep and valeur and valeur != "False":
            valeurs[cle.strip()] = valeur
    return valeurs


def _port_ouvert(hote, port, delai=1.0):
    try:
        with socket.create_connection((hote, int(port)), timeout=delai):
            return True
    except (OSError, ValueError):
        return False


def verifier_postgresql(ctx):
    """PostgreSQL accepte-t-il les connexions, là où config.conf l'attend ?

    Sans « db_host », Odoo passe par le socket Unix local, et pg_isready
    aussi.
    """
    nom = titre(verifier_postgresql)
    config = _config_odoo(ctx)
    hote = config.get("db_host")
    port = config.get("db_port", "5432")
    pg_isready = shutil.which("pg_isready")
    if pg_isready:
        args = ["pg_isready", "-p", port]
        if hote:
            args += ["-h", hote]
        sortie = ctx.lancer(args)
        texte = sortie.stdout.strip() or sortie.stderr.strip()
        if sortie.returncode == 0:
            return Resultat(nom, OK, texte)
        return Resultat(nom, ECHEC, texte or t("no answer"))
    hote = hote or "localhost"
    ctx.noter(f"python3 -c 'socket.create_connection((\"{hote}\", {port}))'")
    if _port_ouvert(hote, port):
        return Resultat(nom, OK, f"{hote}:{port} {t('accepts connections')}")
    return Resultat(nom, ECHEC, f"{hote}:{port} {t('no answer')}")


def verifier_odoo(ctx):
    """Un Odoo écoute-t-il sur le port de config.conf ? Une information :
    un Odoo arrêté n'est pas un défaut."""
    port = _config_odoo(ctx).get("http_port", "8069")
    nom = f"{titre(verifier_odoo)} ({port})"
    ctx.noter(
        f"python3 -c 'socket.create_connection((\"localhost\", {port}))'"
    )
    if _port_ouvert("localhost", port):
        return Resultat(nom, INFO, t("listening"))
    return Resultat(nom, INFO, t("not running"))


def claude_code_present():
    """Vrai si Claude Code est installé pour ce compte : son exécutable sur
    le PATH, ou son dossier ~/.claude, que sa première ouverture crée."""
    return bool(shutil.which("claude")) or os.path.isdir(
        os.path.expanduser("~/.claude")
    )


def verifier_commandes_claude(ctx):
    """Les commandes Claude déployées suivent-elles leur gabarit ?

    Une commande manquante ou périmée est offerte à la résolution « Déployer
    les commandes Claude ». Quand Claude Code est installé sans
    ~/.claude/commands, chaque commande est manquante ; sans Claude Code, la
    vérification est sautée."""
    nom = titre(verifier_commandes_claude)
    if not ctx.etat_commande_claude or not ctx.commandes_claude:
        return Resultat(nom, SAUTE, t("not available"))
    dossier = os.path.expanduser("~/.claude/commands")
    if not os.path.isdir(dossier) and not claude_code_present():
        return Resultat(nom, SAUTE, t("Claude Code is not set up"))
    a_jour = t("up to date")
    hors_depot = t("not in the repository")
    details, a_deployer, fautives = [], [], 0
    ctx.noter(
        f"diff ~/.claude/commands/<{t('name')}>.md conf/<{t('template')}>"
    )
    for commande, gabarit in sorted(ctx.commandes_claude.items()):
        deploye = os.path.join(dossier, f"{commande}.md")
        source = os.path.join(ctx.racine, "conf", gabarit)
        etat = ctx.etat_commande_claude(deploye, source)
        if etat == a_jour:
            continue
        fautives += 1
        details.append(f"/{commande} : {etat}")
        if etat != hors_depot:
            a_deployer.append(
                {"commande": commande, "gabarit": gabarit, "etat": etat}
            )
    if not fautives:
        return Resultat(
            nom, OK, f"{len(ctx.commandes_claude)} {t('up to date')}"
        )
    resolutions = []
    if a_deployer:
        resolutions.append(
            Resolution(
                CLAUDE,
                f"🤖 {t('Deploy the Claude commands:')} {len(a_deployer)}",
                [
                    t(
                        "Each chosen command is copied from its template in conf/ to ~/.claude/commands: a stale copy keeps its git identity, a missing /commit asks for one."
                    )
                ]
                + [f"   /{c['commande']} — {c['etat']}" for c in a_deployer],
                a_deployer,
            )
        )
    return Resultat(
        nom,
        ALERTE,
        f"{fautives} / {len(ctx.commandes_claude)}",
        details,
        resolutions=resolutions,
    )


CLAUDE = "commandes_claude"


def _poids(octets):
    """Une taille lisible, à l'unité du disque : « 3.2 Mio »."""
    for unite, facteur in (("Gio", 1024**3), ("Mio", 1024**2), ("Kio", 1024)):
        if octets >= facteur:
            return f"{octets / facteur:.1f} {unite}"
    return f"{octets} o"


def verifier_journaux(ctx):
    """Les journaux de session du TODO : combien, quel poids, privés ?

    Ils vivent dans le home, communs à tous les checkouts du compte (voir
    todo_journal). Le caviardage n'étant qu'un dernier rempart, un fichier
    ou un dossier lisible par d'autres comptes est une alerte.
    """
    nom = titre(verifier_journaux)
    dossier = todo_journal.dossier_journaux()
    affiche = dossier.replace(os.path.expanduser("~"), "~", 1)
    ctx.noter(f"ls -l {affiche}/{todo_journal.PREFIXE}*{todo_journal.SUFFIXE}")
    if os.environ.get("ERPLIBRE_TODO_LOG", "").strip() == "0":
        return Resultat(nom, SAUTE, t("disabled (ERPLIBRE_TODO_LOG=0)"))
    if not os.path.isdir(dossier):
        return Resultat(nom, INFO, f"{t('no log yet')} · {affiche}")
    journaux = []
    for entree in os.scandir(dossier):
        if (
            entree.name.startswith(todo_journal.PREFIXE)
            and entree.name.endswith(todo_journal.SUFFIXE)
            and entree.is_file(follow_symlinks=False)
        ):
            fiche = entree.stat(follow_symlinks=False)
            journaux.append((fiche.st_mtime, entree.name, fiche))
    if not journaux:
        return Resultat(nom, INFO, f"{t('no log yet')} · {affiche}")
    journaux.sort()
    poids = sum(fiche.st_size for _, _, fiche in journaux)
    resume = f"{len(journaux)} {t('logs')}, {_poids(poids)} · {affiche}"
    details = [
        f"{t('newest:')} {journaux[-1][1]} ({_poids(journaux[-1][2].st_size)})",
        f"{t('oldest:')} {journaux[0][1]}",
    ]
    # La session en cours : un TODO lancé avec ERPLIBRE_TODO_LOG=0, ou dont
    # le journal n'a pas pu s'ouvrir, n'en a pas ; la copie de l'affichage
    # dit si ce que le TODO montre y arrive aussi.
    courant = todo_journal.session_en_cours()
    if courant:
        copie = (
            t("display copied")
            if courant["affichage"]
            else t("display not copied")
        )
        details.append(f"{t('current session:')} {courant['nom']} ({copie})")
    # Les bits « groupe » et « autres » : ni le dossier ni un journal ne
    # doivent en porter.
    ouverts = [n for _, n, fiche in journaux if fiche.st_mode & 0o077]
    if os.stat(dossier).st_mode & 0o077:
        ouverts.insert(0, f"{affiche}/")
    # Le contenu : ce que le caviardage a laissé passer, par fichier et
    # numéro de ligne, sans jamais la valeur.
    ctx.noter("todo_journal.secrets_suspects(<journal>)")
    suspects = []
    for _date, nom_journal, _fiche in journaux:
        for numero, nature in todo_journal.analyser(
            os.path.join(dossier, nom_journal)
        ):
            suspects.append(f"{nom_journal}:{numero} — {t(nature)}")
    if suspects:
        details.append(f"{t('Possible secrets:')} {len(suspects)}")
        details += _limiter(suspects)
        details.append(
            t("Delete these logs, or teach redact_secrets the missing form")
        )
    if ouverts:
        details.append(
            f"{t('readable by others:')} {', '.join(_limiter(ouverts))}"
        )
    if ouverts or suspects:
        return Resultat(nom, ALERTE, resume, details)
    if poids >= JOURNAUX_ALERTE:
        return Resultat(nom, ALERTE, resume, details)
    return Resultat(nom, OK, resume, details)


# Les vérifications, dans l'ordre du rapport : (section, fonction).
VERIFICATIONS = (
    ("code", verifier_conflits),
    ("code", verifier_non_commites),
    ("code", verifier_non_pousses),
    ("code", verifier_formatage),
    ("code", verifier_hygiene),
    ("code", verifier_docs),
    ("code", verifier_manifeste),
    ("code", verifier_branches),
    ("code", verifier_hooks),
    ("environnement", verifier_venv),
    ("environnement", verifier_dependances_venvs),
    ("environnement", verifier_disque),
    ("environnement", verifier_postgresql),
    ("environnement", verifier_odoo),
    ("environnement", verifier_commandes_claude),
    ("environnement", verifier_journaux),
)


def executer(ctx, verification):
    """Le Resultat d'une vérification, commandes comprises ; ne lève pas."""
    ctx.commencer()
    try:
        resultat = verification(ctx)
    except Exception as exc:
        resultat = Resultat(
            titre(verification), ECHEC, f"{type(exc).__name__}: {exc}"
        )
    resultat.commandes = ctx.commandes()
    return resultat


def rendre(resultat):
    """Le bloc d'une vérification : titre, commandes, verdict, détails."""
    lignes = [f"── {resultat.titre} ──"]
    lignes += [f"   $ {c}" for c in resultat.commandes]
    lignes.append(f"   {ICONES[resultat.statut]} {resultat.resume}")
    lignes += [f"      {d}" for d in resultat.details]
    return "\n".join(lignes)


def sommaire(resultats, duree):
    """Le sommaire : une ligne par vérification, puis le décompte."""
    largeur = max((len(r.titre) for r in resultats), default=0)
    lignes = [f"── {t('Summary')} ──"]
    for r in resultats:
        lignes.append(
            f"   {ICONES[r.statut]} {r.titre:<{largeur}}  {r.resume}"
        )
    comptes = [
        f"{sum(1 for r in resultats if r.statut == s)} {ICONES[s].strip()}"
        for s in ORDRE_STATUTS
        if any(r.statut == s for r in resultats)
    ]
    lignes.append(f"   {' · '.join(comptes)}   ({duree:.1f} s)")
    return "\n".join(lignes)


def libelle_portee(ctx):
    return (
        f"{t('Files:')} {t(LIBELLES_FICHIERS[ctx.portee_fichiers])}"
        f" · {t('Repositories:')} {t(LIBELLES_DEPOTS[ctx.portee_depots])}"
    )


LIBELLES_FICHIERS = {
    FICHIERS_NON_COMMITES: "uncommitted",
    FICHIERS_DEPUIS_BASE: "changed since master",
    FICHIERS_TOUS: "every tracked file",
}
LIBELLES_DEPOTS = {
    DEPOTS_ERPLIBRE: "ERPLibre only",
    DEPOTS_TOUS: "ERPLibre and addons",
}


def lancer(ctx, verifications=None, sortie=print):
    """Lance les vérifications, affiche chaque bloc dès qu'il est prêt,
    puis le sommaire. Rend la liste des Resultat."""
    debut = time.monotonic()
    sortie(f"{t('Healthcheck')} — {libelle_portee(ctx)}")
    liste = list(verifications or VERIFICATIONS)
    resultats = []
    section = None
    # Toutes en parallèle, chacune avec son contexte ; l'affichage suit
    # l'ordre de la liste, un bloc dès que lui et ceux qui le précèdent sont
    # finis : le rapport est le même d'une passe à l'autre.
    with ThreadPoolExecutor(max_workers=max(1, len(liste))) as pool:
        futurs = [
            pool.submit(executer, ctx.pour_verification(), verification)
            for _nom_section, verification in liste
        ]
        for (nom_section, _verification), futur in zip(liste, futurs):
            if nom_section != section:
                section = nom_section
                sortie(f"\n━━ {t(SECTIONS[section])} ━━")
            resultat = futur.result()
            resultats.append(resultat)
            sortie(rendre(resultat))
    sortie("")
    sortie(sommaire(resultats, time.monotonic() - debut))
    resolutions = [r for x in resultats for r in x.resolutions]
    if resolutions:
        sortie("")
        sortie(rendre_resolutions(resolutions))
    return resultats


def rendre_resolutions(resolutions):
    """Le bloc « Résolution » : l'explication de chaque résolution, et pour
    celles qui agissent, l'entrée apparue dans le menu."""
    lignes = [f"── {t('Resolution')} ──"]
    for resolution in resolutions:
        lignes += [f"   {ligne}" for ligne in resolution.lignes]
        if resolution.actionnable:
            lignes.append(f"   → {t('Menu entry:')} {resolution.libelle}")
    if any(r.actionnable for r in resolutions):
        lignes.append(
            f"   {t('These entries now appear in the menu, under Resolution.')}"
        )
    return "\n".join(lignes)


def choisir_depots(depots, demander, sortie, decrire=None, tous=None):
    """Les dépôts que l'utilisateur choisit parmi `depots`, numérotés :
    plusieurs numéros séparés par des espaces ou des virgules, des plages
    (« 2-3 »), « a » pour tous, 0 ou Entrée pour revenir sans rien choisir.
    Une saisie dont une partie est fautive est refusée en entier, puis
    redemandée : une faute ne retient jamais en silence une partie de la
    sélection. Une fin d'entrée (Ctrl+D) vaut retour. `decrire(élément)`
    rend la ligne d'un élément, l'écart au gel d'un dépôt par défaut ;
    `tous` est le libellé de « a »."""
    decrire = decrire or (lambda depot: _ligne_gel(depot).strip())
    while True:
        for numero, depot in enumerate(depots, 1):
            sortie(f"   [{numero}] {decrire(depot)}")
        sortie(f"   [a] {tous or t('All repositories')}")
        sortie(f"   {todo_couleur.retour()}")
        try:
            reponse = demander(
                f"💬 {t('Repositories, numbers separated by spaces (a = all): ')}"
            )
        except EOFError:
            print()
            return []
        reponse = reponse.strip().lower()
        if reponse in ("", "0"):
            return []
        rangs = container_runtime.lire_selection(
            "all" if reponse == "a" else reponse, len(depots)
        )
        if rangs is not None:
            return [depots[rang] for rang in rangs]
        sortie(f"{t('Error, cannot understand value')} '{reponse}'")


def _afficher_commande(sortie):
    """Le `noter` de `freeze_resolution` : chaque commande s'affiche au
    moment où elle tourne, comme celles des vérifications."""
    return lambda commande: sortie(f"   $ {commande}")


def executer_resolution(
    ctx,
    resolution,
    demander=None,
    sortie=print,
    mettre_a_jour_venv=None,
    deployer_commande_claude=None,
):
    """Lance `resolution` sur les dépôts que l'utilisateur choisit. Rend
    True si quelque chose a changé. `demander` vaut `input` par défaut, lu
    à l'appel. `mettre_a_jour_venv(choix)` met à jour un venv : celle du
    TODO, qui sait installer un lock et faire le rapport.
    `deployer_commande_claude(commande, gabarit)` déploie une commande
    Claude : celle du TODO, qui sait garder ou demander l'identité git."""
    demander = demander or input
    if resolution.cle == HOOKS_GIT:
        return _installer_hooks(ctx, demander, sortie)
    if resolution.cle == CLAUDE:
        return _deployer_commandes_claude(
            resolution.depots, demander, sortie, deployer_commande_claude
        )
    if resolution.cle == VENVS_OBSOLETES:
        return _remplacer_venvs_obsoletes(
            ctx, resolution.depots, demander, sortie
        )
    if resolution.cle == PAQUETS_DE_TROP:
        return _retirer_paquets(ctx, resolution.depots, demander, sortie)
    if resolution.cle == REGENERER:
        return _regenerer_manifeste(ctx, resolution.depots, demander, sortie)
    if resolution.cle == MAJ_VENVS:
        return _mettre_a_jour_venvs(
            resolution.depots, demander, sortie, mettre_a_jour_venv
        )
    if resolution.cle == freeze_resolution.REMETTRE:
        return _remettre_au_gel(ctx, resolution.depots, demander, sortie)
    if resolution.cle == freeze_resolution.MAJ_GEL:
        return _mettre_a_jour_gel(ctx, resolution.depots, demander, sortie)
    return False


def _oui(demander, question):
    """Vrai sur un oui explicite à `question` ; Entrée et Ctrl+D valent
    non."""
    try:
        reponse = demander(question)
    except EOFError:
        return False
    return reponse.strip().lower() in ("y", "yes", "o", "oui")


def _installer_hooks(ctx, demander, sortie):
    """Pose les hooks git par todo_etat.installer_hooks_git. Une autre
    valeur de core.hooksPath n'est remplacée que sur un oui."""
    actuel = todo_etat._git(ctx.racine, "config", "--get", "core.hooksPath")
    if actuel and os.path.normpath(actuel) != todo_etat.CHEMIN_HOOKS_GIT:
        sortie(f"{t('Another hooks path is already set: ')}{actuel}")
        if not _oui(demander, f"💬 {t('Replace it? (y/N): ')}"):
            sortie(t("Nothing changed."))
            return False
    reussi, lignes = todo_etat.installer_hooks_git(
        ctx.racine,
        noter=lambda commande: sortie(
            f"   $ {commande.replace(ctx.racine, '.')}"
        ),
    )
    for ligne in lignes:
        sortie(f"   {ligne}")
    sortie(
        f"✅ {t('Git hooks installed!')}"
        if reussi
        else f"❌ {t('Git hooks not installed.')}"
    )
    return reussi


def _deployer_commandes_claude(commandes, demander, sortie, deployer):
    sortie(t("Claude commands to deploy:"))
    choisies = choisir_depots(
        commandes,
        demander,
        sortie,
        decrire=lambda c: f"/{c['commande']} — {c['etat']}",
        tous=t("All commands"),
    )
    if not choisies or deployer is None:
        sortie(t("Nothing changed."))
        return False
    change = False
    for commande in choisies:
        sortie(
            f"   $ cp conf/{commande['gabarit']}"
            f" ~/.claude/commands/{commande['commande']}.md"
        )
        change = (
            bool(deployer(commande["commande"], commande["gabarit"])) or change
        )
    return change


def _lancer_dans_le_terminal(ctx):
    """`lancer(commande)` par défaut des résolutions : la commande tourne
    depuis la racine, dans le terminal, et rend son code de sortie."""
    return lambda commande: subprocess.run(commande, cwd=ctx.racine).returncode


def _remplacer_venvs_obsoletes(ctx, venvs, demander, sortie, lancer=None):
    """Installe la version du catalogue qui remplace chaque venv choisi si
    son venv manque, puis supprime le venv obsolète : chaque étape sur un
    oui. L'installation rend sa version active ; une installation ratée
    garde le venv obsolète."""
    lancer = lancer or _lancer_dans_le_terminal(ctx)
    sortie(t("Obsolete Odoo venvs:"))
    choisis = choisir_depots(
        venvs,
        demander,
        sortie,
        decrire=lambda c: f"{c['venv']} → {c['remplacant'] or '—'}",
        tous=t("All venvs"),
    )
    if not choisis:
        sortie(t("Nothing changed."))
        return False
    change = False
    for choix in choisis:
        sortie(f"── {choix['venv']} ──")
        cle = choix["remplacant"]
        if cle and not os.path.isdir(os.path.join(ctx.racine, f".venv.{cle}")):
            commande = [
                "./script/version/update_env_version.py",
                "--erplibre_version",
                cle,
                "--install_dev",
            ]
            question = (
                t(
                    "Install %s? It becomes the active version, and takes a while (y/N): "
                )
                % cle
            )
            if not _oui(demander, f"💬 {question}"):
                sortie(t("Nothing changed."))
                continue
            sortie(f"   $ {shlex.join(commande)}")
            code = lancer(commande)
            if code:
                sortie(
                    f"❌ {shlex.join(commande)} : {t('failure, code')} {code}"
                )
                continue
            change = True
        chemin = os.path.join(ctx.racine, choix["venv"])
        question = t("Delete the obsolete venv %s? (y/N): ") % choix["venv"]
        if not _oui(demander, f"💬 {question}"):
            continue
        sortie(f"   $ rm -rf {choix['venv']}")
        shutil.rmtree(chemin, ignore_errors=True)
        if os.path.isdir(chemin):
            sortie(f"❌ {t('Could not delete')} {choix['venv']}")
            continue
        sortie(f"✅ {t('Deleted:')} {choix['venv']}")
        change = True
    return change


def _retirer_paquets(ctx, paquets, demander, sortie, lancer=None):
    """Désinstalle de leur venv les paquets choisis, d'un seul pip."""
    lancer = lancer or _lancer_dans_le_terminal(ctx)
    sortie(t("Packages nothing requires:"))
    choisis = choisir_depots(
        paquets,
        demander,
        sortie,
        decrire=lambda p: f"{p['paquet']} {p['version']} — {p['venv']}",
        tous=t("All packages"),
    )
    if not choisis:
        sortie(t("Nothing changed."))
        return False
    change = False
    for venv in dict.fromkeys(p["venv"] for p in choisis):
        noms = [p["paquet"] for p in choisis if p["venv"] == venv]
        commande = [
            os.path.join(venv, "bin", "python"),
            "-m",
            "pip",
            "uninstall",
            "-y",
            *noms,
        ]
        sortie(f"   $ {shlex.join(commande)}")
        code = lancer(commande)
        if code:
            sortie(f"❌ pip uninstall : {t('failure, code')} {code}")
        else:
            sortie(f"✅ {t('Uninstalled:')} {', '.join(noms)}")
            change = True
    return change


def _regenerer_manifeste(ctx, depots, demander, sortie, lancer=None):
    """Régénère le manifeste local et synchronise, après confirmation.
    Agit sur tout le checkout : aucun choix de dépôt. `lancer(commande)`
    rend le code de sortie, `subprocess.run` dans le terminal par
    défaut."""
    sortie(
        f"{len(depots)} {t('repositories target an older freeze in the local manifest.')}"
    )
    try:
        reponse = demander(
            f"💬 {t('Regenerate the local manifest and sync? (y/N): ')}"
        )
    except EOFError:
        reponse = ""
    if reponse.strip().lower() not in ("y", "yes", "o", "oui"):
        sortie(t("Nothing changed."))
        return False
    sortie(f"   $ {COMMANDE_REGENERER}")
    lancer = lancer or (
        lambda commande: (
            subprocess.run(shlex.split(commande), cwd=ctx.racine).returncode
        )
    )
    code = lancer(COMMANDE_REGENERER)
    sortie(
        f"✅ {t('Local manifest regenerated.')}"
        if code == 0
        else f"❌ {COMMANDE_REGENERER} : {t('failure, code')} {code}"
    )
    return code == 0


def _remettre_au_gel(ctx, depots, demander, sortie):
    sortie(t("Repositories to put back on their freeze:"))
    depots = choisir_depots(depots, demander, sortie)
    if not depots:
        sortie(t("Nothing changed."))
        return False
    change = False
    for depot in depots:
        reussi, message = freeze_resolution.remettre_au_gel(
            ctx.racine, depot, noter=_afficher_commande(sortie)
        )
        change = change or reussi
        sortie(f"   {'✅' if reussi else '❌'} {depot['path']} — {message}")
    return change


def _mettre_a_jour_gel(ctx, depots, demander, sortie):
    sortie(t("Repositories whose freeze moves to HEAD:"))
    depots = choisir_depots(depots, demander, sortie)
    if not depots:
        sortie(t("Nothing changed."))
        return False
    sortie(t("Checking that each HEAD is pushed…"))
    publies = []
    for depot in depots:
        publie, detail = freeze_resolution.publication(
            ctx.racine, depot, noter=_afficher_commande(sortie)
        )
        if publie:
            publies.append(depot)
            sortie(f"   ✅ {depot['path']} — {t('pushed on')} {detail}")
        elif publie is False:
            sortie(
                f"   ⚠️  {depot['path']} — {t('not pushed, push it first:')}"
                f" {detail}"
            )
        else:
            sortie(f"   ❌ {depot['path']} — {detail}")
    if not publies:
        sortie(t("Nothing changed."))
        return False
    changes, sans_base = freeze_resolution.mettre_a_jour_gel(
        ctx.racine, publies
    )
    if not changes:
        sortie(t("Nothing changed."))
        return False
    sortie(f"✅ {t('Freeze updated in:')} {', '.join(changes)}")
    if sans_base:
        sortie(
            t(
                "Their fork-upstream-freeze-revision is removed: make repo_freeze UPSTREAM=1 computes it again."
            )
        )
    sortie(t("Commit manifest/ to share the new freeze."))
    return True


SECTIONS = {"code": "Code checks", "environnement": "Environment checks"}
