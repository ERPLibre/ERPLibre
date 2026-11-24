#!/usr/bin/env python3
# © 2021-2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Exécute UN scénario du générateur de code, de façon synchrone.

    scenario_odoo.py --json FICHIER --name NOM --run-id ID
                     [--detail SORTIE.json] [--coverage]
                     [--keep-cache DOSSIER] [--racine DOSSIER]

Lancé par run_odoo_scenarios.py, un processus par scénario, dans la
session que le lanceur lui ouvre. Chaque étape est un sous-processus du
MÊME groupe, sans session propre : le killpg du lanceur atteint Odoo.

Les étapes d'un scénario « run_test_exec » : copie du dépôt dans un bac à
sable (sans .git ni setup), réécriture du hooks.py de chaque module
générateur pour qu'il génère dans le bac, git init et commit des copies,
config.conf dont l'addons_path pointe sur les copies, contrôle git des
modules, restauration d'une base, installation, search_class_model,
installation et test du générateur (le code régénéré doit être identique
au code commité), suppression de la base, puis restauration des fichiers
déclarés. Une étape qui rend un code non nul arrête les suivantes, sauf la
suppression de la base et la restauration des fichiers.

Chaque commande s'annonce, une fois finie, par une ligne au format

    PASS|FAIL [NOM] [12.345s] Execute "<commande>"

et les étapes internes (copie, hooks, git init, config) par une ligne
« · étape … » : la liste des commandes et de leur issue se compare ainsi
ligne à ligne d'un passage à l'autre. Le bac et la base sont annoncés au
début (« bac : », « base : »).

VERDICT, dans le code de sortie : 0 si toutes les étapes rendent 0 ET
qu'aucune ligne d'erreur n'échappe aux listes d'ignore de journal_odoo —
Odoo journalise une ERROR et sort pourtant en 0. 1 sinon ; 2 pour un
fichier de scénarios invalide. La sortie finit par un résumé : l'étape
fautive et les lignes d'erreur retenues.

SIGTERM (ou SIGINT) : l'étape en cours et ses descendants reçoivent
SIGTERM, puis SIGKILL après ARRET_ETAPE secondes ; la base du scénario est
supprimée et les fichiers déclarés du dépôt d'origine restaurés s'ils
étaient propres au départ ; sortie en 143 (130 pour SIGINT). Un SIGKILL
ne laisse rien faire : la campagne supprime alors les bases du passage.

--detail écrit une entrée par étape au format de unit_file.py (id,
classe, nom, duree, etat, message), que --junit et --slowest lisent.
"""

import argparse
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time

_RACINE = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)
if _RACINE not in map(os.path.abspath, sys.path):
    sys.path.append(_RACINE)

from script import lib_processus  # noqa: E402
from script.test import journal_odoo, scenarios_odoo  # noqa: E402

ROUGE = "\033[0;31m"
VERT = "\033[0;32m"
JAUNE = "\033[0;33m"
FIN = "\033[0m"

CHECK_GIT = "./script/code_generator/check_git_change_code_generator.sh"

# Secondes laissées à l'étape interrompue pour sortir après SIGTERM, puis
# à la suppression de la base : leur somme tient dans la grâce de 60 s de
# la campagne.
ARRET_ETAPE = 10
DELAI_DROP = 40

# Lignes d'erreur reprises dans le résumé : le bilan du lanceur n'affiche
# que les 12 dernières lignes d'un journal.
ERREURS_AU_RESUME = 8


class Interrompu(BaseException):
    """Levé par le gestionnaire de SIGTERM ou SIGINT. BaseException : un
    « except Exception » d'une étape ne l'avale pas."""

    def __init__(self, signum):
        super().__init__(signum)
        self.signum = signum


def _interrompre(signum, _cadre):
    raise Interrompu(signum)


def _ignorer(_signum, _cadre):
    """Gestionnaire du démontage : un second signal n'interrompt pas la
    suppression de la base. Une fonction Python et non SIG_IGN, que les
    processus lancés hériteraient."""


def descendants(pid=None):
    """Les PID des descendants de `pid` (ce processus par défaut), lus
    dans /proc ; vide hors de Linux."""
    pid = pid or os.getpid()
    enfants = {}
    try:
        entrees = os.listdir("/proc")
    except OSError:
        return []
    for nom in entrees:
        if not nom.isdigit():
            continue
        try:
            with open(f"/proc/{nom}/stat", encoding="ascii") as fh:
                champs = fh.read().rsplit(")", 1)[1].split()
        except (OSError, IndexError, UnicodeDecodeError):
            continue
        if champs[0] == "Z":
            continue
        enfants.setdefault(int(champs[1]), []).append(int(nom))
    trouves = []
    a_voir = [pid]
    while a_voir:
        for enfant in enfants.get(a_voir.pop(), []):
            trouves.append(enfant)
            a_voir.append(enfant)
    return trouves


def _ancetre_existant(racine, chemin):
    """(dossier existant le plus proche de `chemin`, `chemin` relatif à
    lui) : git cherche le dépôt depuis ce dossier, même quand le fichier,
    voire son répertoire, a été supprimé."""
    absolu = os.path.normpath(os.path.join(racine, chemin))
    dossier = os.path.dirname(absolu)
    while dossier and not os.path.isdir(dossier):
        dossier = os.path.dirname(dossier)
    return dossier, os.path.relpath(absolu, dossier)


def chemin_propre(racine, chemin):
    """Vrai si git ne voit aucun changement sur `chemin` (relatif à
    `racine`) dans son dépôt ; faux aussi hors d'un dépôt."""
    dossier, relatif = _ancetre_existant(racine, chemin)
    res = subprocess.run(
        ["git", "status", "--porcelain", "--", relatif],
        cwd=dossier,
        capture_output=True,
        text=True,
        # Hors du groupe du terminal : un Ctrl+C pendant le démontage ne
        # le tue pas, ce qui le ferait passer pour un dépôt modifié.
        start_new_session=True,
        stdin=subprocess.DEVNULL,
    )
    return res.returncode == 0 and not res.stdout.strip()


def restaurer_chemin(racine, chemin):
    """`git checkout -- chemin` dans son dépôt ; rend (code, sortie)."""
    dossier, relatif = _ancetre_existant(racine, chemin)
    res = subprocess.run(
        ["git", "checkout", "--", relatif],
        # Hors du groupe du terminal : un Ctrl+C du démontage ne coupe pas
        # la restauration.
        start_new_session=True,
        cwd=dossier,
        capture_output=True,
        text=True,
    )
    return res.returncode, (res.stdout + res.stderr).strip()


class Scenario:
    """Un scénario et ce que son passage a produit : étapes, lignes
    retenues, base, bac."""

    def __init__(
        self,
        e,
        run_id,
        racine,
        version,
        coverage=False,
        keep_cache=None,
        sortie=None,
    ):
        self.e = e
        self.nom = e["test_name"]
        self.run_id = run_id
        self.racine = racine
        self.version = version
        self.coverage = coverage
        self.keep_cache = keep_cache
        self.sortie = sortie or sys.stdout
        self.etapes = []
        self.erreurs = []
        self.avertissements = []
        # (étape, code) de la première étape fautive.
        self.fautive = None
        # Vrai dès qu'une étape rend un code non nul : les suivantes ne
        # tournent plus, sauf drop et file_to_restore.
        self.arrete = False
        self.base = None
        self.base_creee = False
        self.restauration_lancee = False
        self.bac = None
        self.processus = None
        self.etape_en_cours = None
        self.interruption = None
        self.demontage = []
        # Chemins déclarés du dépôt d'origine, propres au départ : les
        # seuls que le démontage restaure.
        self.origine_propre = [
            c
            for c in scenarios_odoo.chemins_origine(e)
            if chemin_propre(racine, c)
        ]

    # ── sortie et notes ────────────────────────────────────────────────

    def ecrire(self, texte):
        self.sortie.write(texte)
        self.sortie.flush()

    def noter(self, etape, duree, etat, message=""):
        self.etapes.append(
            {
                "id": f"{self.nom}.{etape}",
                "classe": self.nom,
                "nom": etape,
                "duree": round(duree, 4),
                "etat": etat,
                "message": message,
            }
        )
        if etat != "ok" and self.fautive is None:
            self.fautive = (etape, message.split("\n", 1)[0])

    def retenir(self, texte):
        """Classe les lignes de `texte` ; rend les erreurs retenues."""
        erreurs, avertissements = journal_odoo.classer_lignes(texte)
        self.erreurs += erreurs
        self.avertissements += avertissements
        return erreurs

    def echec_interne(self, etape, message, debut):
        """Une étape interne échoue : elle arrête le scénario."""
        self.ecrire(f"{message}\n")
        self.retenir(message)
        self.arrete = True
        self.noter(etape, time.monotonic() - debut, "echec", message)

    # ── étapes ─────────────────────────────────────────────────────────

    def commande(self, cmd, etape):
        """Lance `cmd` depuis la racine, sortie et erreur recopiées au
        journal à mesure, puis annonce son issue. Rend son code."""
        debut = time.monotonic()
        self.etape_en_cours = etape
        self.processus = subprocess.Popen(
            cmd,
            cwd=self.racine,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        morceaux = []
        for brut in iter(self.processus.stdout.readline, b""):
            ligne = brut.decode("utf-8", errors="replace")
            morceaux.append(ligne)
            self.ecrire(ligne)
        rc = self.processus.wait()
        self.processus.stdout.close()
        self.processus = None
        self.etape_en_cours = None
        duree = time.monotonic() - debut
        entete = (
            f"{'FAIL' if rc else 'PASS'} [{self.nom}] [{duree:.3f}s]"
            f' Execute "{" ".join(cmd)}"'
        )
        self.ecrire(f"\n\n{entete}\n\n")
        erreurs = self.retenir(entete + "\n" + "".join(morceaux))
        if rc:
            self.arrete = True
            message = f"code {rc}"
        elif erreurs:
            message = "ligne(s) d'erreur malgré le code 0"
        else:
            message = ""
        if erreurs:
            message += "\n" + "\n".join(erreurs)
        self.noter(etape, duree, "echec" if message else "ok", message)
        return rc

    def silencieuse(self, cmd, cwd=None):
        """Une commande dont seule la sortie standard sert ; son code est
        ignoré, comme l'étape qu'elle sert le prévoit."""
        res = subprocess.run(
            cmd,
            cwd=cwd or self.racine,
            capture_output=True,
        )
        return res.returncode, res.stdout.decode("utf-8", errors="replace")

    def interne(self, etape, action):
        """Exécute `action()` comme étape interne : une exception l'échoue
        et arrête le scénario. Rend vrai si elle a réussi."""
        debut = time.monotonic()
        try:
            action()
        except Exception as exc:  # noqa: BLE001
            message = f"{type(exc).__name__}: {exc}"
            self.ecrire(f"· étape {etape} : {message}\n")
            self.retenir(message)
            self.arrete = True
            self.noter(etape, time.monotonic() - debut, "erreur", message)
            return False
        duree = time.monotonic() - debut
        self.ecrire(f"· étape {etape} : ok ({duree:.1f} s)\n")
        self.noter(etape, duree, "ok")
        return True

    def creer_bac(self):
        if self.keep_cache:
            os.makedirs(self.keep_cache, exist_ok=True)
            self.bac = self.keep_cache
        else:
            # Dans le TMPDIR que le lanceur donne à l'élément.
            self.bac = tempfile.mkdtemp()
        return self.bac

    # ── déroulé ────────────────────────────────────────────────────────

    def derouler(self):
        if self.e["sorte"] == "run_command":
            script = self.e["script"]
            if self.coverage and self.e.get("script_coverage"):
                script = self.e["script_coverage"]
            self.commande([script], "script")
            return
        self.derouler_exec()

    def derouler_exec(self):
        e = self.e
        pmc = e["path_module_check"]
        generated = e.get("generated_module")
        generate_path = e.get("generate_path")
        tested = e.get("tested_module")
        search_class = e.get("search_class_module")
        install_path = e.get("install_path")
        init = e.get("init_module_name")
        lst_init = init.split(",") if init else None
        origine_pmc = pmc
        if search_class:
            if install_path is not None:
                template_a_generer = os.path.join(install_path, tested)
            elif generate_path:
                template_a_generer = os.path.join(generate_path, tested)
            else:
                template_a_generer = os.path.join(pmc, tested)
            if generate_path is not None:
                module_a_generer = os.path.join(generate_path, search_class)
            else:
                module_a_generer = os.path.join(pmc, search_class)
        else:
            template_a_generer = module_a_generer = None

        generique = False
        destination = None
        new_config = None
        if e["run_in_sandbox"]:
            racine_bac = self.creer_bac()
            self.ecrire(f"bac : {racine_bac}\n")
            workspace = os.path.join(racine_bac, "workspace")
            os.mkdir(workspace)
            a_ajouter = []
            a_retirer = []
            debut = time.monotonic()
            if not os.path.exists(os.path.join(self.racine, pmc)):
                self.echec_interne(
                    "copie",
                    f"{ROUGE}Error{FIN} var path_module_check '{pmc}' not"
                    " exist.",
                    debut,
                )
                return
            copie_pmc = pmc
            pmc = os.path.normpath(os.path.join(workspace, pmc))
            if generated and pmc.endswith("/" + generated):
                generique = True
                destination = pmc[: -(len(generated) + 1)]
                source = copie_pmc[: -(len(generated) + 1)]
            elif search_class and pmc.endswith("/" + search_class):
                destination = pmc[: -(len(search_class) + 1)]
                source = copie_pmc[: -(len(search_class) + 1)]
            else:
                destination = pmc
                source = copie_pmc
            a_ajouter.append(destination)
            a_retirer.append(source)
            ignore = shutil.ignore_patterns(".git", "setup")
            if not self.interne(
                "copie",
                lambda: shutil.copytree(
                    os.path.join(self.racine, source),
                    destination,
                    ignore=ignore,
                ),
            ):
                return
            for module in tested.split(",") if tested else ():
                if not self.hooks(
                    module,
                    generated,
                    workspace,
                    source,
                    destination,
                    a_ajouter,
                    a_retirer,
                ):
                    return
            self.git_init(a_ajouter)
            new_config = os.path.join(workspace, "config.conf")

            def ecrire_config():
                with open(os.path.join(self.racine, "config.conf")) as fh:
                    texte = fh.read()
                texte = scenarios_odoo.update_config(
                    texte, a_retirer, a_ajouter, module=generated
                )
                with open(new_config, "w") as fh:
                    fh.write(texte)

            if not self.interne("config", ecrire_config):
                return

        if install_path is None:
            install_path = pmc
        elif e["run_in_sandbox"]:
            install_path = os.path.normpath(
                os.path.join(self.bac, "workspace", install_path)
            )

        for module in lst_init or ():
            self.commande([CHECK_GIT, pmc, module], f"check_git {module}")
        # Un pathspec par module : la liste entière, « a,b », n'en
        # désigne aucun et le contrôle passerait toujours.
        for module in tested.split(",") if tested else ():
            self.commande([CHECK_GIT, pmc, module], f"check_git {module}")
        if self.arrete:
            return

        script_apres = e.get("script_after_init_check")
        if script_apres:
            self.commande([script_apres], "script_after_init_check")

        self.base = scenarios_odoo.nom_base(self.run_id, self.nom)
        self.ecrire(f"base : {self.base}\n")
        if not self.arrete:
            self.restauration_lancee = True
            rc = self.commande(
                [
                    "./script/database/db_restore.py",
                    "--database",
                    self.base,
                    "--image",
                    e["restore_db_image_name"],
                ],
                "restore",
            )
            self.base_creee = rc == 0

        if not self.arrete and lst_init:
            if self.coverage:
                script = (
                    "./script/addons/coverage_install_addons_dev.sh"
                    if tested
                    else "./script/addons/coverage_install_addons.sh"
                )
            else:
                script = (
                    "./script/addons/install_addons_dev.sh"
                    if tested
                    else "./script/addons/install_addons.sh"
                )
            cmd = [script, self.base, ",".join(lst_init)]
            if new_config:
                cmd.append(new_config)
            self.commande(cmd, "install")

        if not self.arrete and search_class and generated:
            self.commande(
                [
                    "./script/code_generator/search_class_model.py",
                    "--quiet",
                    "-d",
                    module_a_generer,
                    "-t",
                    template_a_generer,
                ],
                "search_class",
            )

        chemin_teste = destination if generique else install_path
        if not self.arrete and tested and generated:
            script = "./script/code_generator/" + (
                "coverage_install_and_test_code_generator.sh"
                if self.coverage
                else "install_and_test_code_generator.sh"
            )
            if new_config:
                cmd = [
                    script,
                    self.base,
                    tested,
                    chemin_teste,
                    generated,
                    new_config,
                ]
            else:
                cmd = [script, self.base, tested, install_path, generated]
            self.commande(cmd, "cg_test")

        if self.base_creee:
            if self.keep_cache:
                self.ecrire(f"base gardée : {self.base}\n")
            else:
                self.commande(
                    ["./odoo_bin.sh", "db", "drop", self.base], "drop"
                )

        if e.get("file_to_restore"):
            depot = origine_pmc if e["file_to_restore_origin"] else pmc
            self.file_to_restore(depot, e["file_to_restore"])

    def hooks(
        self, module, generated, workspace, source, destination, ajout, retrait
    ):
        """Copie le dépôt du module générateur `module` s'il n'est pas
        celui déjà copié, puis réécrit son hooks.py dans le bac. Rend faux
        si le scénario doit s'arrêter."""
        debut = time.monotonic()
        etape = f"hooks {module}"
        _rc, trouve = self.silencieuse(
            ["find", f"./odoo{self.version}/addons/", "-name", module]
        )
        if not trouve:
            self.echec_interne(
                etape,
                f"{ROUGE}Error{FIN} cannot find module '{module}' in"
                f" ./odoo{self.version}/addons/.",
                debut,
            )
            return False
        premier = trouve.strip().split("\n")[0]
        parent = os.path.dirname(premier)
        if source != parent:
            nouvelle = os.path.join(
                os.path.dirname(destination), os.path.basename(parent)
            )
            ignore = shutil.ignore_patterns(".git", "setup")
            if not self.interne(
                f"copie {os.path.basename(parent)}",
                lambda: shutil.copytree(
                    os.path.join(self.racine, parent), nouvelle, ignore=ignore
                ),
            ):
                return False
            ajout.append(nouvelle)
            retrait.append(parent)
        dans_le_bac = os.path.normpath(os.path.join(workspace, premier))
        # Le module généré n'est cherché que sous un « addons/ » à la
        # racine du bac ; sinon, le bac du dépôt copié.
        cible = destination
        if generated and os.path.isdir(os.path.join(workspace, "addons")):
            _rc, genere = self.silencieuse(
                ["find", "./addons/", "-name", generated], cwd=workspace
            )
            if genere:
                cible = os.path.normpath(
                    os.path.join(
                        workspace,
                        os.path.dirname(genere.strip().split("\n")[0]),
                    )
                )
        hook = os.path.join(dans_le_bac, "hooks.py")
        if not os.path.exists(hook):
            self.echec_interne(etape, f"Hook file '{hook}' not exist.", debut)
            return False
        with open(hook) as fh:
            texte = fh.read()
        try:
            texte = scenarios_odoo.reecrire_hooks(texte, cible)
        except scenarios_odoo.CleHooksAbsente:
            self.echec_interne(
                etape,
                f"Cannot find keys '{list(scenarios_odoo.CLES_HOOKS)}' in"
                f" {hook}",
                debut,
            )
            return False
        with open(hook, "w") as fh:
            fh.write(texte)
        duree = time.monotonic() - debut
        self.ecrire(f"· étape {etape} : ok ({duree:.1f} s)\n")
        self.noter(etape, duree, "ok")
        return True

    def git_init(self, dossiers):
        """git init, add et commit dans chaque copie. Leurs codes ne
        comptent pas : un commit manqué se voit au contrôle git qui suit,
        où tout paraît non suivi."""
        for dossier in dossiers:
            debut = time.monotonic()
            codes = [
                self.silencieuse(cmd, cwd=dossier)[0]
                for cmd in (
                    ["git", "init", "."],
                    ["git", "add", "."],
                    ["git", "commit", "-am", "'first commit'"],
                )
            ]
            duree = time.monotonic() - debut
            etape = f"git_init {os.path.basename(dossier)}"
            self.ecrire(f"· étape {etape} : codes {codes} ({duree:.1f} s)\n")
            self.noter(etape, duree, "ok", f"codes {codes}")

    def file_to_restore(self, depot, liste):
        """Les fichiers déclarés doivent apparaître supprimés (« D ») dans
        `depot` : ils sont alors restaurés par git, sinon l'étape échoue."""
        debut = time.monotonic()
        fichiers = liste.strip().split(",")
        _rc, etat = self.silencieuse(
            ["git", "status", "-s"], cwd=os.path.join(self.racine, depot)
        )
        etat = etat.rstrip("\n")
        if all(f"D {f}" in etat for f in fichiers):
            codes = [
                self.silencieuse(
                    ["git", "checkout", f],
                    cwd=os.path.join(self.racine, depot),
                )[0]
                for f in fichiers
            ]
            if any(codes):
                self.echec_interne(
                    "file_to_restore",
                    f"FAIL - git checkout {fichiers} : codes {codes}",
                    debut,
                )
                return
            duree = time.monotonic() - debut
            self.ecrire(f"· étape file_to_restore : ok ({duree:.1f} s)\n")
            self.noter("file_to_restore", duree, "ok")
        else:
            self.echec_interne(
                "file_to_restore",
                f"\n\n{ROUGE}FAIL{FIN} - inspect to delete file {fichiers}",
                debut,
            )

    # ── interruption ───────────────────────────────────────────────────

    def arreter_etape(self, recu=None):
        """SIGTERM à l'étape en cours et à ses descendants, SIGKILL après
        ARRET_ETAPE secondes, puis récolte. La base n'est supprimée qu'une
        fois ce qui l'utilisait arrêté.

        `recu` : le signal qui interrompt le scénario. Chef de son groupe,
        un SIGTERM reçu est celui que le lanceur a envoyé au groupe ENTIER :
        Odoo l'a déjà, et un second SIGTERM le ferait sortir sur-le-champ,
        sans écrire ses données de couverture. On attend alors seulement."""
        chef = os.getpgid(0) == os.getpid()
        if chef and recu == signal.SIGTERM:
            pass
        elif chef:
            # Le groupe est fait de ses seuls descendants ; le gestionnaire
            # courant ignore le signal pour ce processus.
            try:
                os.killpg(0, signal.SIGTERM)
            except OSError:
                pass
        else:
            for pid in descendants():
                try:
                    os.kill(pid, signal.SIGTERM)
                except OSError:
                    pass
        echeance = time.monotonic() + ARRET_ETAPE
        while self._a_arreter(chef) and time.monotonic() < echeance:
            if self.processus is not None:
                try:
                    self.processus.wait(timeout=0.1)
                except subprocess.TimeoutExpired:
                    pass
            else:
                time.sleep(0.1)
        for pid in self._a_arreter(chef):
            try:
                os.kill(pid, signal.SIGKILL)
            except OSError:
                pass
        if self.processus is not None:
            try:
                self.processus.wait(timeout=5)
            except subprocess.TimeoutExpired:
                pass
            if self.processus.stdout:
                self.processus.stdout.close()
            self.processus = None

    @staticmethod
    def _a_arreter(chef):
        """Les processus que l'arrêt doit voir finir. Chef de son groupe :
        tous les MEMBRES du groupe hors soi, y compris un Odoo dont
        l'enveloppe bash est déjà morte au SIGTERM et qui, rattaché à
        init, n'est plus un descendant. Sinon : les descendants."""
        if chef:
            trouves = lib_processus.membres(os.getpid())
            if trouves is not None:
                return [p for p in trouves if p != os.getpid()]
        return descendants()

    def demonter(self):
        """Après une interruption : supprime la base du scénario et
        restaure les fichiers déclarés du dépôt d'origine."""
        if self.restauration_lancee and not self.keep_cache:
            try:
                res = subprocess.run(
                    ["./odoo_bin.sh", "db", "drop", "--if-exists", self.base],
                    cwd=self.racine,
                    capture_output=True,
                    text=True,
                    timeout=DELAI_DROP,
                )
                self.demontage.append(
                    f"base {self.base} supprimée"
                    if res.returncode == 0
                    else f"suppression de {self.base} : code {res.returncode}"
                )
            except subprocess.TimeoutExpired:
                self.demontage.append(
                    f"suppression de {self.base} : délai de {DELAI_DROP} s"
                )
        for chemin in self.origine_propre:
            rc, _sortie = restaurer_chemin(self.racine, chemin)
            self.demontage.append(
                f"{chemin} restauré"
                if rc == 0
                else f"{chemin} : restauration en échec ({rc})"
            )

    # ── ensemble ───────────────────────────────────────────────────────

    def lancer(self):
        """Exécute le scénario et rend son code de sortie. Une fois le
        déroulé fini ou interrompu, SIGTERM et SIGINT sont ignorés : le
        démontage, le détail et le résumé s'écrivent jusqu'au bout."""
        try:
            try:
                self.derouler()
                code = 1 if (self.arrete or self.erreurs) else 0
            except Exception as exc:  # noqa: BLE001
                message = f"{type(exc).__name__}: {exc}"
                self.ecrire(f"{message}\n")
                self.retenir(message)
                self.noter("interne", 0.0, "erreur", message)
                code = 1
            signal.signal(signal.SIGTERM, _ignorer)
            signal.signal(signal.SIGINT, _ignorer)
        except Interrompu as exc:
            signal.signal(signal.SIGTERM, _ignorer)
            signal.signal(signal.SIGINT, _ignorer)
            self.interruption = (exc.signum, self.etape_en_cours)
            self.arreter_etape(exc.signum)
            self.demonter()
            code = 128 + exc.signum
        if self.bac and not self.keep_cache:
            shutil.rmtree(self.bac, ignore_errors=True)
        elif self.bac:
            self.ecrire(f"bac gardé : {self.bac}\n")
        return code

    def resume(self, code):
        """Les dernières lignes du journal : l'issue, l'étape fautive et
        les lignes d'erreur retenues. Ni « error » ni « warning » hors des
        lignes citées : le relevé de make_test.log les compterait."""
        lignes = [f"── résumé [{self.nom}]"]
        if self.interruption:
            signum, etape = self.interruption
            lignes.append(
                f"{JAUNE}ARRÊTÉ [{self.nom}]{FIN} : signal {signum}"
                f" pendant l'étape « {etape or '-'} »"
            )
            lignes += [f"  {d}" for d in self.demontage]
            return lignes
        if code == 0:
            lignes.append(
                f"{VERT}OK [{self.nom}]{FIN} : {len(self.etapes)} étape(s),"
                f" aucune erreur retenue,"
                f" {len(self.avertissements)} avertissement(s)"
            )
            return lignes
        for erreur in self.erreurs[:ERREURS_AU_RESUME]:
            lignes.append(f"  {erreur.strip()[:200]}")
        if len(self.erreurs) > ERREURS_AU_RESUME:
            lignes.append(
                f"  … et {len(self.erreurs) - ERREURS_AU_RESUME} autre(s)"
            )
        etape, detail = self.fautive or ("?", "")
        lignes.append(
            f"{ROUGE}ÉCHEC [{self.nom}]{FIN} : étape « {etape} »"
            f"{f' ({detail})' if detail else ''},"
            f" {len(self.erreurs)} ligne(s) d'erreur retenue(s)"
        )
        return lignes


def ecrire_detail(chemin, etapes):
    """Le détail par étape, écrit d'un bloc : le lanceur ne lit jamais un
    fichier à moitié écrit."""
    provisoire = chemin + ".tmp"
    with open(provisoire, "w", encoding="utf-8") as fh:
        json.dump(etapes, fh, ensure_ascii=False)
    os.replace(provisoire, chemin)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--json", required=True)
    parser.add_argument("--name", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--detail")
    parser.add_argument("--coverage", action="store_true")
    parser.add_argument("--keep-cache", metavar="DOSSIER")
    parser.add_argument("--racine", default=_RACINE)
    args = parser.parse_args(argv)
    signal.signal(signal.SIGTERM, _interrompre)
    signal.signal(signal.SIGINT, _interrompre)
    racine = os.path.abspath(args.racine)
    os.chdir(racine)
    try:
        with open(args.json, encoding="utf-8") as fh:
            entrees = scenarios_odoo.charger_et_valider(fh.read())
        e = scenarios_odoo.entree(entrees, args.name)
        version = scenarios_odoo.lire_version(racine)
    except (OSError, ValueError, KeyError) as exc:
        print(f"{ROUGE}scénario {args.name} : {exc}{FIN}")
        return 2
    scenario = Scenario(
        e,
        args.run_id,
        racine,
        version,
        coverage=args.coverage,
        keep_cache=args.keep_cache,
    )
    code = scenario.lancer()
    if args.detail:
        try:
            ecrire_detail(args.detail, scenario.etapes)
        except OSError:
            pass
    print()
    for ligne in scenario.resume(code):
        print(ligne)
    sys.stdout.flush()
    return code


if __name__ == "__main__":
    sys.exit(main())
