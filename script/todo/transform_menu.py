#!/usr/bin/env python3
# © 2021-2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Le menu « Transform data » : décrire un fichier externe, puis le copier.

Le moteur vit dans `script/data/external_file.py` et tourne en
SOUS-PROCESSUS, sous l'interpréteur que `transform_setup.engine_python()`
désigne — le venv dédié pour Excel et Access, celui du CLI pour les
formats en pur stdlib. Même séparation que `lib_analyse` appelant `psql`
plutôt que d'importer psycopg2 : le CLI n'a pas à porter les
bibliothèques de lecture.

L'ordre du dialogue est la règle, pas une préférence : rapport, questions,
puis MARCHE À BLANC, et l'écriture seulement après. C'est la convention du
dépôt pour l'action de menu qui écrit — « une question posée avant de
savoir ce qui sera touché n'est pas un consentement : c'est un pari ».

Ce que ce mixin EMPRUNTE à `TODO`
---------------------------------
`_is_yes`, `_is_yes_default_yes`, `fill_help_info`, `execute`,
`db_manager`, `_dir_path`, et — pour l'anonymisation d'une base —
`_monitoring_restore` et `_monitoring_write_flow`. La liste est écrite
ici parce qu'un emprunt tacite se casse en silence : une méthode
renommée dans `todo.py` ne lève qu'à l'exécution de l'entrée, et un
bouchon de test qui ne la fournit pas passe au vert sans rien éprouver.

Les deux emprunts de `monitoring` sont VOULUS : `anonymize.py` sait déjà
remplacer les données d'une base, et `_monitoring_write_flow` sait déjà
montrer puis demander avec le nom retapé. Les réécrire ici ferait deux
dialogues à tenir d'accord pour la même chose.
"""

from __future__ import annotations

import datetime
import json
import os
import shlex
import shutil
import subprocess

import click

from script.todo import transform_setup
from script.todo.todo_i18n import t

try:
    from script.todo import todo_file_browser
except Exception:  # pragma: no cover - urwid peut manquer
    todo_file_browser = None

MOTEUR = os.path.join("script", "data", "external_file.py")
SORTIE_PAR_DEFAUT = os.path.join("private", "transform")

# Ce que chaque format peut porter en sortie. Les formats en lecture seule
# n'ont pas de graveur : leur copie repart en .xlsx.
EXTENSION_PAR_FORMAT = {
    "xlsx": ".xlsx",
    "xls": ".xlsx",
    "xlsb": ".xlsx",
    "access": ".xlsx",
    "csv": ".csv",
    "xml": ".xml",
    "json": ".json",
}

CIBLES = ("xlsx", "csv", "json", "xml")

# Ce que le chemin COURT prend, quand l'opérateur refuse les options
# avancées. Sept questions dont chacune a un défaut évident : les répondre
# une par une pour arriver au même endroit fait passer les invites par
# réflexe, et une invite qu'on passe par réflexe ne consent à rien.
#
# `calibre_chiffres` est le seul qui ne suit pas le défaut de son invite :
# le chemin court GARDE les largeurs. L'aperçu dit alors que l'étendue
# mesurée ne borne plus les nombres, ce qui est ce qui rend le raccourci
# honnête — un taux ou une année peut sortir de sa plage.
DEFAUTS_RAPIDES = {
    "feuilles": [],
    "colonnes_intactes": [],
    "nombres": True,
    "calibre_chiffres": True,
    "texte": True,
    "entetes": False,
    "graine": "",
}

# La famille d'une valeur laissée intacte, telle qu'on la nomme à l'écran.
# Une date et un booléen sont de VRAIES valeurs du client : les taire dans
# le bilan laissait croire à une copie entièrement remplacée.
_LIBELLE_INTACTES = {
    "formule": "formula(s)",
    "date": "date(s)",
    "booleen": "boolean(s)",
    "erreur": "error value(s)",
    "binaire": "binary value(s)",
    "texte": "text",
    "nombre": "numeric",
}


class TransformMenuMixin:
    # ------------------------------------------------------------------
    # Menu
    # ------------------------------------------------------------------
    def prompt_execute_transform(self):
        print(f"🪄 {t('Transform your data: read, describe, then copy.')}")
        choices = [
            # « Source » et non « Source file » : l'entrée couvre
            # désormais un fichier ET une base Odoo, et un libellé qui
            # dit « fichier » ferait chercher ailleurs l'anonymiseur de
            # base.
            {"section": t("Source")},
            {"prompt_description": t("Open a file and read its report")},
            {
                "prompt_description": t(
                    "Anonymise an Odoo database or a backup"
                )
            },
            {"section": t("Environment")},
            {"prompt_description": t("Install the reading environment")},
            {"prompt_description": t("What can this machine read?")},
            {"prompt_description": t("Copies produced")},
            {"prompt_description": t("Databases produced")},
        ]
        help_info = self.fill_help_info(choices)

        while True:
            status = click.prompt(help_info)
            print()
            if status == "0":
                return False
            elif status == "1":
                self._transform_open_and_report()
            elif status == "2":
                self._transform_anonymise_base()
            elif status == "3":
                self._transform_install_env()
            elif status == "4":
                self._transform_capabilities()
            elif status == "5":
                self._transform_copies()
            elif status == "6":
                self._transform_bases_produites()
            else:
                print(t("Command not found !"))

    # ------------------------------------------------------------------
    # Le moteur, en sous-processus
    # ------------------------------------------------------------------
    def _transform_run(self, arguments, fmt=None):
        """Lancer le moteur. Rend l'objet JSON, ou None sur erreur.

        stdout ne porte qu'un objet JSON ; stderr porte la progression et
        les traces. Un stdout vide ou inanalysable est traité comme une
        erreur — et non relayé en exception — pour que le menu affiche les
        dernières lignes de stderr plutôt que de tomber à son tour.
        """
        interpreteur = transform_setup.engine_python(fmt)
        racine = transform_setup.racine()
        environnement = dict(os.environ)
        environnement["PYTHONPATH"] = racine
        commande = [interpreteur, os.path.join(racine, MOTEUR)] + list(
            arguments
        )
        try:
            acheve = subprocess.run(
                commande,
                capture_output=True,
                text=True,
                cwd=racine,
                env=environnement,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            print(f"❌ {exc}")
            return None

        for ligne in (acheve.stderr or "").splitlines():
            if ligne.startswith("# "):
                print(f"   {ligne[2:]}")

        try:
            resultat = json.loads(acheve.stdout or "")
        except (ValueError, TypeError):
            print(f"❌ {t('Command not found !')}")
            print(f"   {shlex.join(commande)}")
            for ligne in (acheve.stderr or "").splitlines()[-20:]:
                print(f"   {ligne}")
            return None

        if "erreur" in resultat:
            print(f"❌ {t(resultat['erreur'])}{resultat.get('detail', '')}")
            if resultat.get("conseil"):
                print(f"   → {t(resultat['conseil'])}")
            return None
        return resultat

    # ------------------------------------------------------------------
    # Le fichier d'entrée
    # ------------------------------------------------------------------
    def _on_dir_selected(self, chemin):
        """Le chemin choisi dans le navigateur, mis de côté.

        Ce mixin fournit SON rappel au lieu d'emprunter celui de sa classe
        d'accueil : `TODO` nomme le sien `on_dir_selected` et pose
        `dir_path`, tandis que le préfixé vit sur le gestionnaire de bases,
        qui n'est pas un mixin mais un objet à part. Emprunter faisait
        lever `AttributeError` à l'ouverture du navigateur — donc au
        premier usage de l'entrée, et sur la première ligne du menu.

        Le navigateur sort de sa boucle lui-même après avoir appelé le
        rappel : celui-ci n'a que le chemin à retenir.
        """
        self._dir_path = chemin

    def _transform_select_file(self):
        """Le parcours d'abord, la saisie en repli.

        La garde d'import est celle de `database_manager` : urwid peut
        manquer, et sans elle « p » lèverait sur None.
        """
        depart = os.path.join(os.getcwd(), SORTIE_PAR_DEFAUT)
        if not os.path.isdir(depart):
            depart = os.getcwd()
        if todo_file_browser is not None:
            self._dir_path = ""
            navigateur = todo_file_browser.FileBrowser(
                depart, self._on_dir_selected
            )
            navigateur.run_main_frame()
            if self._dir_path and os.path.isfile(self._dir_path):
                print(self._dir_path)
                return self._dir_path
        reponse = input(
            t("Enter to accept, p to browse, or type a path: ")
        ).strip()
        if not reponse or reponse == "0":
            return None
        chemin = os.path.expanduser(reponse)
        if not os.path.isfile(chemin):
            print(f"❌ {t('Not an ordinary file.')} {chemin}")
            return None
        return chemin

    # ------------------------------------------------------------------
    # Le rapport
    # ------------------------------------------------------------------
    def _transform_render_report(self, rapport):
        lignes = []
        nom = os.path.basename(rapport.get("chemin", ""))
        taille = rapport.get("taille", 0)
        lignes.append(f"🪄 {nom} — {taille} o — {rapport.get('format', '')}")
        if rapport.get("divergence"):
            lignes.append(
                f"   ⚠ {t('Contents do not match the extension: read as ')}"
                f"{rapport.get('format', '')}"
            )
        if rapport.get("encodage"):
            lignes.append(
                f"   {t('Encoding detected by ')}"
                f"{t(rapport['encodage_source'])}: {rapport['encodage']}"
            )
            lignes.append(
                f"   {t('Delimiter detected by ')}"
                f"{t(rapport['delimiteur_source'])}:"
                f" {rapport['delimiteur']!r}"
            )

        feuilles = rapport.get("feuilles") or []
        if feuilles:
            lignes.append("")
            lignes.append(f"   {len(feuilles)} {t('sheet(s)')}")
        for feuille in feuilles:
            marque = f" ({t('hidden')})" if feuille.get("masquee") else ""
            lignes.append(
                f"   {feuille['nom']}{marque}"
                f"   {feuille['lignes']} × {feuille['colonnes_n']}"
                f"   {feuille['formules']} {t('formula(s)')}"
            )
            if feuille.get("formules_litteral"):
                lignes.append(
                    f"      ⚠ {feuille['formules_litteral']}"
                    f" {t('formula(s) holding a text literal')}"
                )
            for colonne in feuille.get("colonnes", [])[:12]:
                borne = ""
                if colonne.get("min") is not None:
                    borne = f"  {colonne['min']}..{colonne['max']}"
                plancher = "  ⛔" if colonne.get("plancher") else ""
                lignes.append(
                    f"      {colonne['index']:>3} "
                    f"{str(colonne['etiquette'] or ''):<22}"
                    f"{colonne['type']:<9}"
                    f"{colonne['remplies']:>6} {t('row(s)')}"
                    f"{colonne['distinctes']:>6}"
                    f" {t('distinct value(s)')}{borne}{plancher}"
                )
            reste = len(feuille.get("colonnes", [])) - 12
            if reste > 0:
                lignes.append(f"      … {reste}")
            # Les colonnes au-delà du plafond des exemples n'en portent
            # pas : une colonne sans exemple se lit comme une colonne
            # vide, et le taire faisait juger une colonne sur rien.
            manquants = feuille.get("exemples_manquants") or 0
            if manquants:
                lignes.append(
                    f"      ⚠ {manquants} {t('column(s) without examples')}"
                )

        requetes = rapport.get("requetes") or []
        if requetes:
            # Nommées, non comptées : une base dont le travail vit dans
            # ses requêtes se transmet amputée, et un chiffre ne dit pas
            # ce qui manque.
            lignes.append("")
            lignes.append(f"   {len(requetes)} {t('saved query(ies)')}")
            for nom in requetes[:12]:
                lignes.append(f"      {nom}")
            if len(requetes) > 12:
                lignes.append(
                    f"      … {len(requetes) - 12} {t('more, not listed')}"
                )

        hors = rapport.get("hors_cellules") or {}
        if hors:
            lignes.append("")
            lignes.append(f"   {t('Text outside cells')}")
            if hors.get("macros"):
                lignes.append(f"   ⚠ {t('VBA macros present')}")
            elif rapport.get("format") == "xlsx":
                lignes.append(f"   {t('No VBA macro')}")
            for cle, libelle in (
                ("croises", "pivot table(s)"),
                ("graphiques", "chart(s) with cached series"),
                ("feuilles_graphiques", "chart sheet(s)"),
                ("images", "image(s) and drawing(s)"),
                ("liens_externes", "external link(s)"),
                ("hyperliens", "cell hyperlink(s)"),
                ("commentaires", "comment(s)"),
                ("auteurs_commentaires", "comment author(s)"),
                ("entetes_pieds", "header(s)/footer(s)"),
                ("validations", "validation(s)"),
                ("conditionnelles", "conditional format(s)"),
            ):
                if hors.get(cle):
                    lignes.append(f"   {hors[cle]} {t(libelle)}")
            if hors.get("createur") or hors.get("modifie_par"):
                lignes.append(
                    f"   {t('Author')}: {hors.get('createur') or ''}"
                    f" / {hors.get('modifie_par') or ''}"
                )
            if hors.get("cibles_liens"):
                lignes.append(
                    f"   {t('Link targets')}:"
                    f" {', '.join(hors['cibles_liens'][:5])}"
                )
            if hors.get("plages_nommees"):
                lignes.append(
                    f"   {t('named range(s)')}:"
                    f" {', '.join(hors['plages_nommees'][:8])}"
                )

        comptes = rapport.get("comptes") or {}
        lignes.append("")
        lignes.append(
            f"   {t('Anonymisable')}:"
            f" {comptes.get('texte', 0)} {t('text')},"
            f" {comptes.get('nombre', 0)} {t('numeric')}"
        )
        lignes.append(
            f"   {t('word(s) in the pool')}: {rapport.get('vivier', 0)}"
        )
        intacts = []
        for cle, libelle in (
            ("formule", "formula(s)"),
            ("date", "date(s)"),
            ("booleen", "boolean(s)"),
            ("erreur", "error value(s)"),
            ("binaire", "binary value(s)"),
        ):
            if comptes.get(cle):
                intacts.append(f"{comptes[cle]} {t(libelle)}")
        if intacts:
            lignes.append(f"   {t('Left intact')}: {', '.join(intacts)}")
        for avertissement in rapport.get("avertissements", []):
            lignes.append(f"   ⚠ {t(avertissement)}")
        return "\n".join(lignes)

    # ------------------------------------------------------------------
    # Les questions
    # ------------------------------------------------------------------
    @staticmethod
    def _transform_ask(libelle):
        """La réponse, ou None quand l'opérateur tape « 0 ».

        Une sortie doit exister à CHAQUE question : s'apercevoir à la
        onzième qu'on a ouvert le mauvais fichier ne doit pas obliger à
        répondre à tout puis à refuser un nom de fichier.
        """
        reponse = input(libelle).strip()
        return None if reponse == "0" else reponse

    def _transform_ask_options(self, rapport):
        """Les réponses, ou None si l'opérateur renonce."""
        print(f"   {t('0 to cancel')}")
        options = {}
        reponse = self._transform_ask(t("Anonymise this file? (y/N): "))
        if reponse is None or not self._is_yes(reponse):
            return None

        cible = self._transform_ask(
            t("Convert at the same time? (xlsx/csv/json/xml, empty = keep): ")
        )
        if cible is None:
            return None
        cible = cible.strip().lower()
        if cible and cible not in CIBLES:
            print(f"❌ {t('Format not recognised: ')}{cible}")
            return None
        options["conversion"] = cible

        # La table AVANT l'écran : elle dit si ce fichier appartient à
        # un lot déjà entamé, et l'écran montre alors les lignes
        # d'en-tête qu'un fichier précédent a fait corriger. La poser
        # après l'écran laissait cette mémoire hors de vue.
        reponse = self._transform_ask(
            t("Mapping table to reuse (empty = a new one): ")
        )
        if reponse is None:
            return None
        options["table_chemin"] = (
            os.path.expanduser(reponse) if reponse else ""
        )

        # L'écran AVANT les questions de portée : c'est lui qui répond
        # aux deux qu'une invite ne sait pas poser — quelles lignes
        # nomment les colonnes, et lesquelles rester intactes. Il rend
        # `{}` pour dire « pose-moi les questions », ce qui laisse la
        # suite se dérouler comme avant.
        ecran = self._transform_ecran(rapport, options.get("table_chemin"))
        if ecran is None:
            return None
        options.update(ecran)

        reponse = self._transform_ask(t("Advanced options? (y/N): "))
        if reponse is None:
            return None
        if not self._is_yes(reponse):
            # L'écran a pu répondre par feuille : ses réponses passent
            # AVANT les défauts, sans quoi refuser les options avancées
            # effacerait ce qu'on vient de cocher.
            for cle, valeur in DEFAUTS_RAPIDES.items():
                options.setdefault(cle, valeur)
            if "colonnes_intactes_index_par_feuille" in options:
                options["colonnes_intactes"] = []
            self._transform_dire_les_defauts(options)
            return self._transform_ask_hors_cellules(rapport, options)

        noms = [f["nom"] for f in rapport.get("feuilles") or []]
        if len(noms) > 1:
            reponse = self._transform_ask(
                t("Sheets to process (empty = all): ")
            )
            if reponse is None:
                return None
            demandees = [n.strip() for n in reponse.split(",") if n.strip()]
            resolues = []
            for demandee in demandees:
                trouve = next(
                    (n for n in noms if n.strip().lower() == demandee.lower()),
                    None,
                )
                if trouve is None:
                    manque = t(
                        "The selection matches no sheet;"
                        " nothing was written."
                    )
                    print(f"❌ {manque} {demandee}")
                    return None
                resolues.append(trouve)
            options["feuilles"] = resolues
            if resolues:
                print(f"   {', '.join(resolues)}")

        if "colonnes_intactes_index_par_feuille" in options:
            # L'écran a répondu par feuille, ce que cette invite ne sait
            # pas faire : la reposer inviterait à une réponse GLOBALE qui
            # gèlerait la même colonne sur toutes les feuilles.
            options["colonnes_intactes"] = []
        else:
            reponse = self._transform_ask(
                t("Columns to leave untouched (empty = none): ")
            )
            if reponse is None:
                return None
            options["colonnes_intactes"] = [
                c.strip() for c in reponse.split(",") if c.strip()
            ]

        reponse = self._transform_ask(t("Replace numbers? (Y/n): "))
        if reponse is None:
            return None
        options["nombres"] = self._is_yes_default_yes(reponse)
        if options["nombres"]:
            # Posée SOUS la question des nombres : sans eux elle n'a pas
            # d'objet, et une invite qui ne change rien apprend à passer
            # les invites.
            reponse = self._transform_ask(t("Keep the digit count? (y/N): "))
            if reponse is None:
                return None
            options["calibre_chiffres"] = self._is_yes(reponse)

        reponse = self._transform_ask(t("Replace text? (Y/n): "))
        if reponse is None:
            return None
        options["texte"] = self._is_yes_default_yes(reponse)

        reponse = self._transform_ask(
            t("Anonymise the header row too? (y/N): ")
        )
        if reponse is None:
            return None
        options["entetes"] = self._is_yes(reponse)

        reponse = self._transform_ask(
            t("Random seed (empty = not reproducible): ")
        )
        if reponse is None:
            return None
        options["graine"] = reponse

        return self._transform_ask_hors_cellules(rapport, options)

    def _transform_ask_hors_cellules(self, rapport, options):
        """Ce qu'un classeur porte HORS des cellules : macros, graphiques.

        Ces deux-là ne sont pas des options avancées et restent posées
        dans les deux chemins : elles ne se voient pas dans les cellules,
        elles ne se devinent pas, et la réponse change ce que la copie
        porte. Elles ne se posent que si le fichier en a et que la copie
        peut les porter — une question dont la réponse ne change rien
        apprend à passer les questions.
        """
        hors = rapport.get("hors_cellules") or {}
        garde_xlsm = (options["conversion"] or rapport["format"]) == "xlsx"
        if hors.get("macros") and garde_xlsm:
            reponse = self._transform_ask(
                t("Keep the VBA macros in the copy? (y/N): ")
            )
            if reponse is None:
                return None
            options["garder_macros"] = self._is_yes(reponse)
        if hors.get("graphiques") and garde_xlsm:
            reponse = self._transform_ask(
                t("Keep the charts in the copy? (y/N): ")
            )
            if reponse is None:
                return None
            options["garder_graphiques"] = self._is_yes(reponse)
        return options

    @staticmethod
    def _transform_dire_les_defauts(options):
        """Montrer ce que le chemin court a pris, sans le demander.

        Un raccourci qui ne dit pas ce qu'il choisit n'est pas un
        raccourci mais une surprise : l'opérateur consent à ce qu'il LIT.

        Des PHRASES et non un tableau de oui/non : ce sont des décisions
        prises, pas des questions posées, et « Remplacer les nombres →
        oui » se lit comme une invite dont on aurait perdu la réponse.
        """
        # L'écran a pu geler des colonnes, et le chemin court les GARDE :
        # annoncer « aucune colonne laissée intacte » dirait alors le
        # contraire de ce qui s'applique, sur le seul écran où
        # l'opérateur consent.
        gelees = options.get("colonnes_intactes_index_par_feuille") or {}
        combien = sum(len(rangs) for rangs in gelees.values())
        perimetre = (
            f"{combien} {t('column(s) left untouched, chosen on screen')}"
            if combien
            else t("no column left untouched")
        )
        # Un empan VIDE veut dire « cette feuille n'a pas d'en-tête », et
        # l'écran y mène d'une frappe. Sa première ligne est alors de la
        # donnée et se fait remplacer : annoncer l'en-tête protégé dirait
        # le contraire de ce qui s'applique. Une feuille ABSENTE de la
        # table veut dire « mesure-la », ce qui laisse l'en-tête en place.
        empans = options.get("entetes_par_feuille") or {}
        sans_entete = [nom for nom, rangs in empans.items() if not rangs]
        entete = (
            f"{len(sans_entete)} {t('sheet(s) with no header row on screen')}"
            if sans_entete
            else t("the header row is left readable")
        )
        print(f"   {t('Taken as given:')}")
        for ligne in (
            t("every sheet"),
            perimetre,
            t(
                "numbers replaced, widths kept"
                if options.get("calibre_chiffres")
                else "numbers replaced within the measured extent"
            ),
            t("text replaced"),
            entete,
            t("no seed: not reproducible"),
        ):
            print(f"      {ligne}")

    def _transform_ecran(self, rapport, table_chemin=""):
        """Le périmètre choisi à l'écran, ou {} pour les invites.

        Trois issues, et non deux : la spec porte le périmètre, `{}`
        demande les invites, et None annule. Confondre les deux dernières
        supprimerait le repli en silence.
        """
        if not (rapport.get("feuilles") or []):
            return {}
        reponse = self._transform_ask(t("Open the TUI for setup? (Y/n): "))
        if reponse is None:
            return None
        if not self._is_yes_default_yes(reponse):
            return {}
        try:
            from script.todo import transform_form
        except ImportError:  # pragma: no cover - textual peut manquer
            print(
                "   ⚠ %s"
                % t("The screen needs textual; falling back to prompts.")
            )
            return {}
        try:
            spec = transform_form.run_transform_form(
                transform_form.contexte_depuis_rapport(
                    rapport, self._transform_memoire(table_chemin)
                )
            )
        except Exception as exc:  # pragma: no cover - pas de terminal
            # Un écran qui ne peut pas s'ouvrir ne doit pas emporter le
            # travail : les invites savent tout demander.
            print(f"   ⚠ {exc}")
            return {}
        if spec is None:
            return None
        return spec

    @staticmethod
    def _transform_memoire(table_chemin):
        """Les lignes d'en-tête qu'une table de lot se rappelle.

        Lue ICI et non par le moteur : l'écran vit dans le processus du
        menu, et la table est un simple JSON. Une table absente, illisible
        ou d'une version antérieure rend un dictionnaire vide — la mémoire
        est un confort, jamais une condition pour ouvrir l'écran.
        """
        if not table_chemin or not os.path.isfile(table_chemin):
            return {}
        try:
            with open(table_chemin, "r", encoding="utf-8") as flux:
                brut = json.load(flux)
            # Une racine qui n'est pas un dictionnaire — un autre fichier
            # de `private/` désigné à l'invite — lèverait `AttributeError`
            # sur `.get`, hors de ce que la garde attrape, et emporterait
            # l'ouverture de l'écran. Le moteur refusera ce chemin en
            # NOMMANT la table ; ici la mémoire est un confort, et son
            # absence n'a rien à empêcher.
            if not isinstance(brut, dict):
                return {}
            return brut.get("entetes") or {}
        except (OSError, ValueError):
            return {}

    # ------------------------------------------------------------------
    # L'aperçu
    # ------------------------------------------------------------------
    def _transform_preview(self, apercu):
        """Montrer, PUIS demander. False si l'opérateur refuse."""
        print(f"\n   {t('Preview — nothing written yet')}")
        print(
            f"   {apercu.get('remplacees', 0)} {t('cell(s) replaced')}"
            f" — {apercu.get('texte', 0)} {t('text')},"
            f" {apercu.get('nombre', 0)} {t('numeric')}"
        )
        if apercu.get("hors_portee"):
            print(
                f"   {apercu['hors_portee']}"
                f" {t('cell(s) left out of scope')}"
            )
        ecartees = apercu.get("colonnes_ecartees") or []
        if ecartees:
            noms = ", ".join(
                sorted(
                    {str(c["etiquette"]) for c in ecartees if c["etiquette"]}
                )
            )
            print(
                f"   {t('column(s) left alone: they hold identifiers')}:"
                f" {noms}"
            )
        intactes = apercu.get("intactes") or {}
        if intactes:
            # Une date, un booléen, une valeur d'erreur traversent par
            # RÈGLE, non par oubli — et ce sont de vraies valeurs du
            # client. Ne les compter nulle part faisait signer un
            # consentement sur un fichier dont une colonne entière part
            # en clair sans que rien ne le dise.
            detail = ", ".join(
                f"{compte} {t(_LIBELLE_INTACTES.get(famille, famille))}"
                for famille, compte in sorted(intactes.items())
                if compte
            )
            print(f"   ⚠ {t('Left intact')} : {detail}")
        # Le compte par famille dit POURQUOI, non OÙ : sur quarante
        # colonnes, « 7 date(s) laissées » ne dit pas laquelle sort. Le
        # critère est le même quelle que soit la raison — une colonne qui
        # porte quelque chose et dont rien n'a été remplacé part entière.
        # Celles qu'une réponse ou le plancher expliquent sont déjà
        # nommées au-dessus, et n'y reviennent pas.
        en_clair = apercu.get("colonnes_en_clair") or []
        if en_clair:
            noms = ", ".join(
                "%s/%s"
                % (
                    colonne["feuille"],
                    colonne["etiquette"] or "#%s" % colonne["index"],
                )
                for colonne in en_clair
            )
            print(f"   ⚠ {t('column(s) entirely in clear')} : {noms}")
        gardee = apercu.get("entete_gardee") or []
        if gardee:
            # L'empan est MESURÉ, et il porte plusieurs lignes sur un
            # export mis en page : un compteur ne dirait pas qu'un nom est
            # dedans. Chaque valeur se montre donc, avec sa coordonnée.
            print(f"   ⚠ {t('These cells are copied verbatim:')}")
            for cellule in gardee:
                print(f"      {cellule['cellule']}  {cellule['valeur']!r}")
            # Le plafond borne la LISTE, pas le compte : le taire faisait
            # consentir sur un extrait pris pour le tout.
            for nom, omises in sorted(
                (apercu.get("entete_gardee_omises") or {}).items()
            ):
                print(f"      {nom} : {omises} {t('more, not listed')}")
            print("      " + t("Correct the header rows to anonymise them."))
        for exemple in apercu.get("apercu") or []:
            print(
                f"      {exemple['cellule']}"
                f"  {exemple['avant']!r} → {exemple['apres']!r}"
            )
        for fichier in apercu.get("fichiers") or []:
            if fichier:
                print(f"   → {fichier}")
        for avertissement in apercu.get("avertissements") or []:
            print(f"   ⚠ {t(avertissement)}")
        return self._is_yes_default_yes(input(t("Write? (Y/n): ")))

    # ------------------------------------------------------------------
    # La destination
    # ------------------------------------------------------------------
    def _transform_select_destination(self, source, fmt, macros=False):
        """Le chemin de sortie, ou None si l'opérateur renonce.

        Le défaut NE REPREND PAS le nom source : sur un export réel, ce nom
        porte le client, la base ou l'année, et toute l'entrée existe pour
        produire un fichier transmissible. Le nom source reste offert, et
        l'invite dit alors qu'il n'a pas été anonymisé.

        Un classeur qui GARDE ses macros se nomme `.xlsm` : Excel lie
        l'extension au contenu, et refuse d'ouvrir un `.xlsx` qui porte un
        projet VBA. La copie était écrite correctement et n'ouvrait pas.
        """
        horodatage = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
        extension = EXTENSION_PAR_FORMAT.get(fmt, ".out")
        if macros and extension == ".xlsx":
            extension = ".xlsm"
        defaut = os.path.join(
            SORTIE_PAR_DEFAUT, f"{horodatage}.anon{extension}"
        )
        print(f"\n   {t('Destination')}: {defaut}")
        if extension == ".xlsm":
            print(
                "   ⚠ %s"
                % t(
                    "Macros are kept, so the copy is named .xlsm:"
                    " Excel refuses a .xlsx holding a VBA project."
                )
            )
        avis = t(
            "The file name is not anonymised;"
            " the default does not reuse it."
        )
        print(f"   ⚠ {avis}")
        reponse = self._transform_ask(
            t("Enter to accept, p to browse, or type a path: ")
        )
        if reponse is None:
            return None
        if not reponse:
            return defaut
        if reponse.lower() == "p":
            if todo_file_browser is None:
                print(f"   {defaut}")
                return defaut
            depart = os.path.dirname(os.path.abspath(defaut))
            if not os.path.isdir(depart):
                depart = os.getcwd()
            self._dir_path = ""
            navigateur = todo_file_browser.FileBrowser(
                depart, self._on_dir_selected, open_dir=True
            )
            navigateur.run_main_frame()
            if not self._dir_path:
                return None
            choisi = os.path.join(self._dir_path, os.path.basename(defaut))
            print(f"   {choisi}")
            return choisi
        return os.path.expanduser(reponse)

    @staticmethod
    def _transform_table_par_defaut(destination):
        """Le chemin de la table, TOUJOURS sous private/transform/.

        La table porte chaque valeur d'origine en clair : elle
        ré-identifie la copie à elle seule. La poser à côté du fichier à
        transmettre — ce que faisait le défaut, puisque la destination est
        justement choisie hors de private/ — fait partir la clé avec le
        chiffré au premier `zip -r` ou `scp -r` du dossier de livraison.

        Le nom DÉRIVE de la destination, ce qui reste le plus utile pour
        retrouver la table d'une copie une semaine plus tard. Mais il ne
        tient qu'au nom de BASE : deux livraisons rangées par année,
        « 2026/export.xlsx » et « 2027/export.xlsx », donnaient le même
        chemin. L'invite promet « vide = nouvelle » et le moteur chargeait
        la table de la livraison précédente — ses mots, ses nombres, ses
        empans — sans que rien ne signale sa présence, l'écran ayant déjà
        été bâti sur une mémoire vide.

        Un chemin déjà pris prend donc un suffixe frais, et l'appelant le
        DIT. Le partage voulu à l'intérieur d'un lot passe par l'invite,
        où l'opérateur tape le chemin de la table précédente.
        """
        chemin = TransformMenuMixin._transform_table_derivee(destination)
        if not os.path.exists(chemin):
            return chemin
        horodatage = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
        racine = chemin[: -len(".table.json")]
        return f"{racine}-{horodatage}.table.json"

    @staticmethod
    def _transform_table_derivee(destination):
        """Le nom que la destination donne à sa table, SANS voir le disque.

        Séparé pour que l'appelant sache si le chemin retenu est bien
        celui-là — comparer deux chemins vaut mieux que renifler un tiret
        dans un nom de base, qui en porte un dès que la destination garde
        l'horodatage du défaut.
        """
        base = os.path.basename(os.path.splitext(destination)[0])
        return os.path.join(SORTIE_PAR_DEFAUT, f"{base}.table.json")

    def _transform_confirm_overwrite(self, cibles):
        """Le nom tapé en entier, comme le reste du dépôt l'exige."""
        existants = [c for c in cibles if c and os.path.exists(c)]
        if not existants:
            return True
        print(f"   {t('These files would be overwritten: ')}")
        for cible in existants:
            print(f"      {cible}")
        attendu = os.path.basename(existants[0])
        reponse = input(
            t(
                "This file already exists. Type its name in full to"
                " overwrite: "
            )
        ).strip()
        if reponse != attendu:
            print(f"❌ {t('Name does not match, nothing was written.')}")
            return False
        return True

    # ------------------------------------------------------------------
    # Le déroulé complet
    # ------------------------------------------------------------------
    def _transform_open_and_report(self):
        chemin = self._transform_select_file()
        if not chemin:
            return

        format_devine = self._transform_format(chemin)
        if not transform_setup.ensure(format_devine):
            return

        rapport = self._transform_run(["--report", chemin], format_devine)
        if rapport is None:
            return
        print(self._transform_render_report(rapport))

        if rapport.get("arret"):
            print(f"\n❌ {t(rapport['arret'])}")
            return

        options = self._transform_ask_options(rapport)
        if options is None:
            print(t("Nothing to do."))
            return

        sortie_fmt = options["conversion"] or rapport["format"]
        fmt_moteur = self._transform_fmt_moteur(rapport["format"], sortie_fmt)
        destination = self._transform_select_destination(
            chemin, sortie_fmt, options.get("garder_macros")
        )
        if not destination:
            print(t("Nothing to do."))
            return
        options["destination"] = destination
        if not options.get("table_chemin"):
            options["table_chemin"] = self._transform_table_par_defaut(
                destination
            )
            # « vide = nouvelle » est une promesse : le dire quand le nom
            # dérivé était déjà pris, plutôt que d'adopter en silence la
            # table d'une autre livraison.
            if options["table_chemin"] != self._transform_table_derivee(
                destination
            ):
                print(
                    f"   {t('A table of that name exists; using a new one.')}"
                )
        print(f"   {t('Mapping table: ')}{options['table_chemin']}")

        arguments = [
            "--plan",
            chemin,
            "--options",
            json.dumps(options, ensure_ascii=False),
        ]
        if options.get("table_chemin"):
            arguments += ["--table", options["table_chemin"]]
        apercu = self._transform_run(arguments, fmt_moteur)
        if apercu is None:
            return
        if not self._transform_preview(apercu):
            print(t("Nothing to do."))
            return

        if not self._transform_confirm_overwrite(
            apercu.get("fichiers") or [destination]
        ):
            return

        arguments = [
            "--apply",
            chemin,
            "--out",
            destination,
            "--options",
            json.dumps(options, ensure_ascii=False),
        ]
        if options.get("table_chemin"):
            arguments += ["--table", options["table_chemin"]]
        bilan = self._transform_run(arguments, fmt_moteur)
        if bilan is None:
            return
        self._transform_render_bilan(bilan, destination)

    @staticmethod
    def _transform_fmt_moteur(source_fmt, sortie_fmt):
        """Le format qui DÉCIDE de l'interpréteur du moteur.

        Le processus doit lire la source ET écrire la cible : il lui faut
        l'union des bibliothèques. La source seule laissait csv→xlsx
        importer openpyxl sous l'interpréteur du CLI, qui peut ne pas l'avoir ; la
        cible seule enverrait un classeur au même interpréteur, qui ne sait
        pas le lire.
        """
        if source_fmt not in transform_setup.FORMATS_STDLIB:
            return source_fmt
        return sortie_fmt

    def _transform_render_bilan(self, bilan, destination):
        for fichier in bilan.get("fichiers") or [destination]:
            print(f"✅ {t('Written: ')}{fichier}")
        print(
            f"   {bilan.get('remplacees', 0)} {t('cell(s) replaced')}"
            f" — {bilan.get('texte', 0)} {t('text')},"
            f" {bilan.get('nombre', 0)} {t('numeric')}"
        )
        intactes = bilan.get("intactes") or {}
        if intactes:
            detail = ", ".join(
                f"{compte} {t(_LIBELLE_INTACTES.get(famille, famille))}"
                for famille, compte in sorted(intactes.items())
                if compte
            )
            print(f"   {t('Left intact')} : {detail}")
        if bilan.get("hors_portee"):
            print(
                f"   {bilan['hors_portee']}"
                f" {t('cell(s) left out of scope')}"
            )
        hors = bilan.get("hors_cellules") or {}
        # `isinstance(True, int)` vaut True : sans exclure les booléens, le
        # drapeau des macros comptait pour un élément effacé.
        efface = sum(
            v
            for v in hors.values()
            if isinstance(v, int) and not isinstance(v, bool)
        )
        if efface:
            print(f"   {efface} {t('element(s) outside cells wiped')}")
        non_verifiees = bilan.get("valeurs_non_verifiees") or 0
        if non_verifiees:
            print(
                f"   ⚠ {non_verifiees}"
                f" {t('value(s) not verified, above the cap')}"
            )
        print(f"   {t('The original was not modified.')}")
        if bilan.get("table"):
            print(f"   {t('Mapping table written: ')}{bilan['table']}")
            avis = t("This table re-identifies the copy; keep it in private/.")
            print(f"   ⚠ {avis}")
        for avertissement in bilan.get("avertissements") or []:
            print(f"   ⚠ {t(avertissement)}")
        if self._transform_sous_private(destination):
            avis = t(
                "private/ is tracked by git — this file will show in"
                " « git status »."
            )
            print(f"   ⚠ {avis}")

    @staticmethod
    def _transform_sous_private(destination):
        """La destination est-elle sous `private/` du dépôt ?

        Comparaison de `realpath` ancrés : un test de préfixe sur le chemin
        tel qu'il est tapé taisait l'avertissement pour le chemin ABSOLU
        que rend le navigateur — c'est-à-dire le cas le plus courant — et
        le levait à tort pour « privateer/ ».
        """
        prive = os.path.realpath(
            os.path.join(transform_setup.racine(), "private")
        )
        cible = os.path.realpath(os.path.abspath(str(destination)))
        return cible == prive or cible.startswith(prive + os.sep)

    @staticmethod
    def _transform_format(chemin):
        """Le format présumé, pour choisir l'interpréteur AVANT de lire.

        Le moteur retranchera par les octets ; ici l'extension suffit,
        puisqu'il ne s'agit que de savoir s'il faut le venv dédié.
        """
        extension = os.path.splitext(chemin)[1].lower()
        return {
            ".xlsx": "xlsx",
            ".xlsm": "xlsx",
            ".xlsb": "xlsx",
            ".xls": "xls",
            ".mdb": "access",
            ".accdb": "access",
            ".csv": "csv",
            ".xml": "xml",
            ".json": "json",
        }.get(extension, "xlsx")

    # ------------------------------------------------------------------
    # Une base Odoo, ou une sauvegarde
    # ------------------------------------------------------------------
    def _transform_anonymise_base(self):
        """Anonymiser une base Odoo, ou une sauvegarde qui en redevient une.

        Rien n'est réécrit ici : `anonymize.py` sait déjà remplacer les
        données d'une base, et `_monitoring_write_flow` sait déjà montrer
        puis demander, avec le nom retapé pour confirmer. Cette méthode ne
        fait que choisir la SOURCE et, quand c'en était un, refaire un zip.

        Un zip n'est jamais modifié : il est restauré dans une base, qui
        est anonymisée, puis vidée dans un zip NEUF. Une base locale, elle,
        est modifiée EN PLACE — l'invite le dit, et le nom retapé le
        confirme.
        """
        from script.analyse import monitoring

        analyse = next(
            (a for a in monitoring.ANALYSES if a["key"] == "anonymize"), None
        )
        if analyse is None:  # pragma: no cover - la table est en dur
            print(f"❌ {t('Command not found !')}")
            return
        choix = self._transform_anonymise_source()
        if choix is None:
            print(t("Nothing to do."))
            return
        base, depuis_zip = choix
        print()
        print(monitoring.describe_source(monitoring.KIND_DATABASE, base))
        if not depuis_zip:
            # La base MÊME est modifiée : le dire avant, non après.
            print(f"⚠  {t('The database ITSELF is modified; no copy.')}")
        ecrit = self._monitoring_write_flow(analyse, base)
        # APRÈS le travail, et quel que soit son sort : une base restaurée
        # existe sur le serveur même si l'anonymisation a été refusée, et
        # c'est précisément celle-là qu'il faut pouvoir retrouver.
        self._transform_noter_base(base, depuis_zip)
        if not ecrit:
            # Sans cette garde, un renoncement produisait un zip de la
            # base NON anonymisée, annoncé comme le résultat d'une
            # anonymisation — le pire des deux mondes : l'opérateur croit
            # tenir une copie transmissible et tient l'original.
            print(f"   {t('Nothing was written; no backup was drawn.')}")
            print(f"   {t('Database kept: ')}{base}")
            return
        if depuis_zip:
            self._transform_export_zip(base)

    def _transform_anonymise_source(self):
        """(nom de base, venait d'un zip), ou None si l'on renonce.

        Les trois mêmes provenances que « Monitoring », dans le même
        ordre : deux ordres différents dans un même logiciel se paient en
        hésitation à chaque usage.
        """
        print(f"[1] {t('A local database')}")
        print(f"[2] {t('A local backup .zip')}")
        print(f"[3] {t('A remote backup (https + master password)')}")
        print(f"[0] {t('Back')}")
        reponse = click.prompt(t("Command:"), prompt_suffix=" ")
        print()
        if reponse == "1":
            base = self.db_manager.select_database()
            return (base, False) if base else None
        if reponse == "2":
            chemin = self.db_manager.select_backup_path()
            base = self._monitoring_restore(chemin) if chemin else None
            return (base, True) if base else None
        if reponse == "3":
            statut, chemin, _nom = (
                self.db_manager.download_database_backup_cli()
            )
            if statut or not chemin or not os.path.isfile(chemin):
                print(f"❌ {t('The download did not produce a usable file.')}")
                return None
            base = self._monitoring_restore(chemin)
            return (base, True) if base else None
        return None

    def _transform_export_zip(self, base):
        """Vider la base anonymisée dans un zip NEUF.

        Par la sauvegarde d'Odoo lui-même — `odoo_bin.sh db --backup` —
        et non par un `pg_dump` à nous : c'est Odoo qui écrit le
        `dump.sql`, le `filestore/` et le `manifest.json`, donc le format
        est juste par construction. Le zip atterrit dans `image_db/`,
        d'où les sauvegardes viennent et où le navigateur les cherche.

        Un nom déjà pris n'est jamais écrasé en silence : l'invite le dit
        et propose un nom frais, que l'opérateur peut changer.
        """
        defaut = "%s_anon_%s" % (
            base,
            datetime.datetime.now().strftime("%Y%m%d-%H%M%S"),
        )
        nom = self._transform_ask(
            f"{t('Backup name (Enter to accept): ')}{defaut} "
        )
        if nom is None:
            print(t("Nothing to do."))
            return
        nom = (nom or defaut).removesuffix(".zip")
        cible = os.path.join(
            transform_setup.racine(), "image_db", nom + ".zip"
        )
        if os.path.isfile(cible):
            print(f"   {t('These files would be overwritten: ')}")
            print(f"      {cible}")
            if not self._transform_confirm_overwrite([cible]):
                return
        statut, _sortie = self.execute.exec_command_live(
            f"./odoo_bin.sh db --backup --database {base}"
            f" --restore_image {nom}",
            return_status_and_output=True,
            single_source_erplibre=True,
            source_erplibre=False,
        )
        if statut:
            print(f"❌ {t('The download did not produce a usable file.')}")
            return
        print(f"✅ {t('Backup written: ')}{cible}")
        print(f"   {t('The original was not modified.')}")
        print(f"   {t('Database kept: ')}{base}")

    def _transform_noter_base(self, base, depuis_zip):
        """Inscrire la base produite au registre, sans jamais lever.

        Le serveur ne dit pas QUI a créé une base : sans registre, cette
        entrée ne pourrait que lister toutes les bases de la machine, ce
        que le menu Database fait déjà. Le registre est ce qui lui permet
        de ne montrer que ce que Transform data a produit.

        Un registre illisible ou impossible à écrire ne doit pas emporter
        le travail : il est un confort, comme la mémoire de lot.
        """
        registre = os.path.join(SORTIE_PAR_DEFAUT, "bases.json")
        connues = self._transform_bases_lues()
        connues = [b for b in connues if b.get("base") != base]
        connues.append(
            {
                "base": base,
                "depuis_zip": bool(depuis_zip),
                "date": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            }
        )
        try:
            os.makedirs(SORTIE_PAR_DEFAUT, mode=0o700, exist_ok=True)
            with open(registre, "w", encoding="utf-8") as flux:
                json.dump(connues, flux, ensure_ascii=False, indent=1)
        except OSError:
            pass

    @staticmethod
    def _transform_bases_lues():
        """Le registre, ou une liste vide s'il ne se lit pas."""
        registre = os.path.join(SORTIE_PAR_DEFAUT, "bases.json")
        try:
            with open(registre, "r", encoding="utf-8") as flux:
                lues = json.load(flux)
        except (OSError, ValueError):
            return []
        return [b for b in lues if isinstance(b, dict) and b.get("base")]

    def _transform_bases_produites(self):
        """Lister les bases que cette entrée a produites, et les effacer.

        Le même raisonnement que « Copies produites » : sans elle, le
        serveur devient un tas que rien n'annonce, et le bruit finit par
        se lire comme du fond. Une base anonymisée ne porte plus de
        donnée client, mais elle occupe le serveur et elle se confond avec
        une base de travail.

        Une base inscrite au registre peut avoir été détruite ailleurs —
        par le menu Database, par un `db_drop_all`. L'entrée le DIT plutôt
        que de la proposer à l'effacement.
        """
        inscrites = self._transform_bases_lues()
        if not inscrites:
            print(f"   {t('Empty file.')} {SORTIE_PAR_DEFAUT}")
            return
        vivantes = self._transform_bases_vivantes()
        presentes, disparues = [], []
        for entree in inscrites:
            cible = presentes if entree["base"] in vivantes else disparues
            cible.append(entree)
        for entree in presentes:
            marque = "📦" if entree.get("depuis_zip") else "🗄"
            print(f"   {marque} {entree['base']:<40} {entree['date']}")
        print(f"   {len(presentes)} {t('Database:')}")
        if disparues:
            print()
            print(f"   {t('Gone already, only in the register:')}")
            for entree in disparues:
                print(f"      {entree['base']}")
        if not presentes:
            print(t("Nothing to do."))
            return
        print(f"   {t('Use Database to drop one.')}")

    def _transform_bases_vivantes(self):
        """Les bases que le serveur porte VRAIMENT, ou () si on ne sait pas.

        La MÊME commande que `select_database` — `odoo_bin.sh db --list` —
        et non un appel à psql de plus : deux façons de demander la même
        chose se contredisent le jour où l'une change.

        Une liste vide et une ignorance ne se confondent pas : sans
        serveur joignable, tout le registre paraîtrait disparu. Les deux
        rendent `()`, et l'appelant ne propose alors aucun effacement.
        """
        statut, sortie = self.execute.exec_command_live(
            "./odoo_bin.sh db --list",
            return_status_and_output=True,
            quiet=True,
            source_erplibre=False,
            single_source_erplibre=True,
        )
        if statut:
            return ()
        return {ligne.strip() for ligne in sortie if ligne.strip()}

    # ------------------------------------------------------------------
    # L'environnement
    # ------------------------------------------------------------------
    def _transform_install_env(self):
        if transform_setup.available("xlsx"):
            print(f"✅ {t('The environment is ready.')}")
        else:
            transform_setup.create()
        # La PRÉSENCE d'abord, le paquet ensuite. Demander au gestionnaire
        # de paquets si l'outil est là rendait « aucun paquet connu »
        # devant un `mdb-queries` installé — vrai sur une distribution
        # dont ce module ne connaît pas le paquet, et faux sur ce que
        # l'opérateur voit dans son PATH.
        if transform_setup.requetes_access_lisibles():
            print(f"✅ {t('Access saved queries are readable here.')}")
            return
        commande = transform_setup.system_packages_cmd()
        if commande is None:
            print(f"   {t('No package known here for:')} mdb-queries")
            print(
                f"   {t('Install it by hand to read Access saved queries.')}"
            )
            return
        print(f"\n{t('Access files need a system package.')}")
        print(f"{t('The installation requires sudo.')}")
        from script.todo import todo_install

        todo_install.ask_and_install(
            self.execute,
            commande,
            t("Create it now? (Y/n): "),
            self._is_yes_default_yes,
        )

    def _transform_capabilities(self):
        for fmt, disponible in transform_setup.capabilities().items():
            etat = t("readable") if disponible else t("not readable")
            print(f"   {fmt:<8} {etat}")

    def _transform_copies(self):
        """Lister les copies produites, et proposer de les effacer.

        Rien n'est ajouté à `.gitignore` : les copies restent visibles dans
        « git status », ce qui est le rappel qu'elles existent et qu'elles
        portent de la donnée client. Cette entrée est ce qui rend ce choix
        vivable — sans elle, le répertoire deviendrait un tas que rien
        n'annonce, et le bruit finirait par se lire comme du fond.
        """
        if not os.path.isdir(SORTIE_PAR_DEFAUT):
            print(f"   {t('Empty file.')} {SORTIE_PAR_DEFAUT}")
            return
        produites, etrangeres = self._transform_inventaire()
        if not produites and not etrangeres:
            print(f"   {t('Empty file.')} {SORTIE_PAR_DEFAUT}")
            return
        total = 0
        for nom, taille in produites:
            total += taille
            print(f"   {nom:<44} {taille:>10} o")
        print(f"   {len(produites)} {t('File')} — {total} o")
        if etrangeres:
            # Le navigateur de fichiers ouvre son parcours dans ce même
            # répertoire : ce qui s'y trouve n'est pas toujours une copie
            # produite ici, et l'effacement en bloc l'emportait aussi.
            print(f"\n   {t('Not produced here, left alone:')}")
            for nom, taille in etrangeres:
                print(f"   {nom:<44} {taille:>10} o")
        if not produites:
            print(t("Nothing to do."))
            return
        reponse = input(
            t("Delete all copies in private/transform/? (y/N): ")
        ).strip()
        if not self._is_yes(reponse):
            print(t("Nothing to do."))
            return
        for nom, _taille in produites:
            chemin = os.path.join(SORTIE_PAR_DEFAUT, nom)
            try:
                if os.path.isdir(chemin):
                    # Une source à plusieurs feuilles convertie en csv
                    # écrit un RÉPERTOIRE. Il était listé comme un fichier
                    # avec sa taille d'inode, puis laissé sur le disque,
                    # plein de lignes dérivées du client.
                    shutil.rmtree(chemin)
                else:
                    os.unlink(chemin)
            except OSError as exc:
                print(f"   ⚠ {exc}")

    @staticmethod
    def _transform_inventaire():
        """(produites ici, étrangères) — chacune en (nom, octets).

        Ce que l'outil produit se reconnaît à son nom : « .anon. » quelque
        part, ou le suffixe de la table. Tout le reste est à quelqu'un
        d'autre et n'est pas à effacer.
        """
        produites, etrangeres = [], []
        for nom in sorted(os.listdir(SORTIE_PAR_DEFAUT)):
            chemin = os.path.join(SORTIE_PAR_DEFAUT, nom)
            taille = 0
            if os.path.isdir(chemin):
                for racine, _dossiers, fichiers in os.walk(chemin):
                    for fichier in fichiers:
                        try:
                            taille += os.path.getsize(
                                os.path.join(racine, fichier)
                            )
                        except OSError:
                            continue
            else:
                try:
                    taille = os.path.getsize(chemin)
                except OSError:
                    continue
            cible = (
                produites
                if ".anon." in nom or nom.endswith(".table.json")
                else etrangeres
            )
            cible.append((nom, taille))
        return produites, etrangeres
