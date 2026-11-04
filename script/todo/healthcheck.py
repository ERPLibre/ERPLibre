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
"""

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

from script.todo import todo_etat, todo_journal
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
class Resultat:
    """Le verdict d'une vérification et les commandes qui l'ont produit."""

    titre: str
    statut: str
    resume: str
    details: list = field(default_factory=list)
    commandes: list = field(default_factory=list)


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
    "verifier_hooks": "Git hooks",
    "verifier_venv": "Odoo venv",
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
    "verifier_hooks": "🪝",
    "verifier_venv": "🧪",
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
        self._depots = None
        self._status = {}

    # ── commandes ──────────────────────────────────────────────────────

    def commencer(self):
        """Ouvre le relevé des commandes d'une nouvelle vérification."""
        self._commandes = OrderedDict()

    def commandes(self):
        """Les commandes notées, « (×N) » quand une forme s'est répétée."""
        return [
            texte if n == 1 else f"{texte}   (×{n})"
            for texte, n in (self._commandes or {}).items()
        ]

    def noter(self, texte):
        if self._commandes is None:
            return
        with self._verrou:
            self._commandes[texte] = self._commandes.get(texte, 0) + 1

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
        if self._depots is not None:
            return self._depots
        depots = [(".", None)]
        if self.portee_depots == DEPOTS_TOUS:
            from script.git import repo_state

            self.noter(f"cat {repo_state.MANIFESTE_LOCAL}")
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
        self._depots = depots
        return depots

    def plusieurs_depots(self):
        return len(self.depots()) > 1

    def git(self, depot, *args, delai=DELAI_GIT, forme=None):
        """`git -C <dépôt> args`, noté une fois par forme sur plusieurs
        dépôts. `forme` remplace les arguments notés quand l'un d'eux varie
        d'un dépôt à l'autre."""
        cmd = ["git", "-C", depot, *args]
        if forme is not None:
            forme = f"git -C {self.depot_note(depot)} {forme}"
        elif self.marqueur(depot):
            forme = self.afficher(["git", "-C", "<dépôt>", *args])
        return self.lancer(cmd, forme=forme, delai=delai)

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
        with ThreadPoolExecutor(max_workers=8) as pool:
            rendus = list(pool.map(lambda d: fonction(*d), depots))
        return [(d[0], r) for d, r in zip(depots, rendus)]

    def status(self, depot):
        """Les lignes de `git status --porcelain=v2`, en cache par dépôt."""
        if depot not in self._status:
            sortie = self.git(
                depot, "status", "--porcelain=v2", "--untracked-files=normal"
            )
            self._status[depot] = (
                None
                if sortie.returncode
                else [ligne for ligne in sortie.stdout.splitlines() if ligne]
            )
        return self._status[depot]

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
    for depot, attrs in ctx.depots():
        fichiers, raison = ctx.fichiers(depot, attrs)
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


def verifier_manifeste(ctx):
    """L'écart de chaque dépôt d'addons à ce que le manifeste local demande,
    lu par `repo_state.py snapshot`."""
    nom = titre(verifier_manifeste)
    python = ctx.outil("python3") or "python3"
    script = os.path.join("script", "git", "repo_state.py")
    sortie = ctx.lancer(
        [python, script, "snapshot"],
        forme=f"{ctx.relatif(python)} {script} snapshot",
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
    depots = donnees.get("repos") or []
    if not donnees.get("local_manifest") and not depots:
        return Resultat(nom, SAUTE, t("no local manifest"))
    comptes = {}
    details = []
    for depot in depots:
        etat = depot.get("state")
        comptes[etat] = comptes.get(etat, 0) + 1
        if etat in ("decale", "absent", "erreur"):
            details.append(
                f"{etat} : {depot.get('path')}"
                + (f" — {depot.get('error')}" if depot.get("error") else "")
            )
    resume = " · ".join(f"{n} {etat}" for etat, n in sorted(comptes.items()))
    if details:
        return Resultat(nom, ALERTE, resume, _limiter(details))
    return Resultat(nom, OK, resume)


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
    return Resultat(
        nom, OK if icone == todo_etat.OK else ALERTE, texte.strip()
    )


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


def verifier_commandes_claude(ctx):
    """Les commandes Claude déployées suivent-elles leur gabarit ?"""
    nom = titre(verifier_commandes_claude)
    if not ctx.etat_commande_claude or not ctx.commandes_claude:
        return Resultat(nom, SAUTE, t("not available"))
    dossier = os.path.expanduser("~/.claude/commands")
    if not os.path.isdir(dossier):
        return Resultat(nom, SAUTE, t("Claude Code is not set up"))
    a_jour = t("up to date")
    details, fautives = [], 0
    for commande, gabarit in sorted(ctx.commandes_claude.items()):
        deploye = os.path.join(dossier, f"{commande}.md")
        source = os.path.join(ctx.racine, "conf", gabarit)
        ctx.noter(
            f"diff ~/.claude/commands/<{t('name')}>.md conf/<{t('template')}>"
        )
        etat = ctx.etat_commande_claude(deploye, source)
        if etat != a_jour:
            fautives += 1
            details.append(f"/{commande} : {etat}")
    if fautives:
        details.append(t("Redeploy: Execute › GPT code › Claude configs"))
        return Resultat(
            nom,
            ALERTE,
            f"{fautives} / {len(ctx.commandes_claude)}",
            details,
        )
    return Resultat(nom, OK, f"{len(ctx.commandes_claude)} {t('up to date')}")


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
    ("code", verifier_hooks),
    ("environnement", verifier_venv),
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
    resultats = []
    section = None
    for nom_section, verification in verifications or VERIFICATIONS:
        if nom_section != section:
            section = nom_section
            sortie(f"\n━━ {t(SECTIONS[section])} ━━")
        resultat = executer(ctx, verification)
        resultats.append(resultat)
        sortie(rendre(resultat))
    sortie("")
    sortie(sommaire(resultats, time.monotonic() - debut))
    return resultats


SECTIONS = {"code": "Code checks", "environnement": "Environment checks"}
