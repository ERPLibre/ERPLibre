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
"""

from __future__ import annotations

import datetime
import json
import os
import shlex
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


class TransformMenuMixin:
    # ------------------------------------------------------------------
    # Menu
    # ------------------------------------------------------------------
    def prompt_execute_transform(self):
        print(f"🪄 {t('External files: read, describe, then draw a copy.')}")
        choices = [
            {"section": t("File")},
            {"prompt_description": t("Open a file and read its report")},
            {"section": t("Environment")},
            {"prompt_description": t("Install the reading environment")},
            {"prompt_description": t("What can this machine read?")},
            {"prompt_description": t("Copies produced")},
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
                self._transform_install_env()
            elif status == "3":
                self._transform_capabilities()
            elif status == "4":
                self._transform_copies()
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
            return None
        return resultat

    # ------------------------------------------------------------------
    # Le fichier d'entrée
    # ------------------------------------------------------------------
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

        reponse = self._transform_ask(
            t("Mapping table to reuse (empty = a new one): ")
        )
        if reponse is None:
            return None
        options["table_chemin"] = (
            os.path.expanduser(reponse) if reponse else ""
        )

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
        gardee = apercu.get("entete_gardee") or []
        if gardee:
            # La ligne 1 est présumée d'en-tête, jamais mesurée : un CSV
            # sans en-tête, ou un titre de rapport en A1, y met de la
            # donnée. Un compteur ne dirait pas qu'un nom est dedans.
            print(f"   ⚠ {t('Row 1 is copied verbatim as a header row.')}")
            for cellule in gardee:
                print(f"      {cellule['cellule']}  {cellule['valeur']!r}")
            print(
                "      "
                + t(
                    "If it holds data, answer yes to the header question"
                    " and start over."
                )
            )
        non_verifiees = apercu.get("valeurs_non_verifiees") or 0
        if non_verifiees:
            print(
                f"   ⚠ {non_verifiees}"
                f" {t('value(s) not verified, above the cap')}"
            )
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
    def _transform_select_destination(self, source, fmt):
        """Le chemin de sortie, ou None si l'opérateur renonce.

        Le défaut NE REPREND PAS le nom source : sur un export réel, ce nom
        porte le client, la base ou l'année, et toute l'entrée existe pour
        produire un fichier transmissible. Le nom source reste offert, et
        l'invite dit alors qu'il n'a pas été anonymisé.
        """
        horodatage = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
        extension = EXTENSION_PAR_FORMAT.get(fmt, ".out")
        defaut = os.path.join(
            SORTIE_PAR_DEFAUT, f"{horodatage}.anon{extension}"
        )
        print(f"\n   {t('Destination')}: {defaut}")
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
        destination = self._transform_select_destination(chemin, sortie_fmt)
        if not destination:
            print(t("Nothing to do."))
            return
        options["destination"] = destination
        if not options.get("table_chemin"):
            options["table_chemin"] = self._transform_table_par_defaut(
                destination
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
        apercu = self._transform_run(arguments, rapport["format"])
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
        bilan = self._transform_run(arguments, rapport["format"])
        if bilan is None:
            return
        self._transform_render_bilan(bilan, destination)

    def _transform_render_bilan(self, bilan, destination):
        for fichier in bilan.get("fichiers") or [destination]:
            print(f"✅ {t('Written: ')}{fichier}")
        print(
            f"   {bilan.get('remplacees', 0)} {t('cell(s) replaced')}"
            f" — {bilan.get('texte', 0)} {t('text')},"
            f" {bilan.get('nombre', 0)} {t('numeric')}"
        )
        intactes = bilan.get("intactes") or {}
        if intactes.get("formule"):
            print(f"   {intactes['formule']} {t('formula(s) left intact')}")
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
    # L'environnement
    # ------------------------------------------------------------------
    def _transform_install_env(self):
        if transform_setup.available("xlsx"):
            print(f"✅ {t('The environment is ready.')}")
        else:
            transform_setup.create()
        commande = transform_setup.system_packages_cmd()
        if commande is None:
            print(f"   {t('No package known here for:')} mdb-queries")
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
        entrees = sorted(os.listdir(SORTIE_PAR_DEFAUT))
        if not entrees:
            print(f"   {t('Empty file.')} {SORTIE_PAR_DEFAUT}")
            return
        total = 0
        for nom in entrees:
            chemin = os.path.join(SORTIE_PAR_DEFAUT, nom)
            try:
                taille = os.path.getsize(chemin)
            except OSError:
                continue
            total += taille
            print(f"   {nom:<44} {taille:>10} o")
        print(f"   {len(entrees)} {t('File')} — {total} o")
        reponse = input(
            t("Delete all copies in private/transform/? (y/N): ")
        ).strip()
        if not self._is_yes(reponse):
            print(t("Nothing to do."))
            return
        for nom in entrees:
            chemin = os.path.join(SORTIE_PAR_DEFAUT, nom)
            try:
                if os.path.isfile(chemin):
                    os.unlink(chemin)
            except OSError as exc:
                print(f"   ⚠ {exc}")
