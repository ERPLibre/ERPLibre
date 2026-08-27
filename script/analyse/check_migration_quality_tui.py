# © 2021-2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""La qualité d'une migration, palier par palier, en plein écran.

Le rapport texte dit tout d'un coup : sur six paliers il fait plusieurs
centaines de lignes, et ce qu'on cherche — quel palier a perdu quoi — se
trouve quelque part au milieu. Un écran qui se parcourt règle cela.

Les données viennent de `check_migration_quality`, comme le rapport texte.
Deux assemblages sépareraient les deux vues, et l'on finirait par lire deux
états contradictoires de la même migration.
"""

import os
import subprocess
import sys

sys.path.append(
    os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))
)

from script.analyse import check_migration_quality as quality  # noqa: E402
from script.todo import migration_status as status  # noqa: E402

try:
    from script.todo.todo_i18n import t
except Exception:  # pragma: no cover - repli si i18n indisponible

    def t(key: str) -> str:
        return key


# Les commandes se lancent depuis la RACINE : les chemins qu'elles portent
# — « script/odoo/migration/… » — y sont relatifs, et les lancer d'ailleurs
# les rend introuvables.
REPO_ROOT = os.path.normpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")
)

CSS = """
Screen { layout: vertical; }
#head { height: 3; padding: 0 1; background: $panel; color: $text; }
#body { height: 1fr; }
#left { width: 40; border-right: solid $accent; }
#pane { width: 1fr; padding: 0 1; }
"""


def rows(lst_snapshot, dct=None):
    """Un palier par ligne, le bilan, puis les trois sections de revue.

    Le bilan APRÈS les paliers et non en tête : on descend la liste comme
    on a vécu la migration, et la question « qu'est-ce qu'il en reste » se
    pose une fois qu'on a vu le chemin. Ce qui suit — verdicts, où lire,
    quoi vérifier — répond à « et maintenant ».

    `dct` se passe pour éviter la lecture du fichier de progression :
    autrement la liste dépend de ce qu'une migration a laissé sur CE
    poste, et deux exécutions ne rendent pas la même chose.
    """
    lst = []
    presents = [x for x in lst_snapshot if x.get("exists")]
    for index, etat in enumerate(lst_snapshot):
        if not etat.get("exists"):
            lst.append(
                {
                    "kind": "missing",
                    "label": f"⚠️ {etat['database'][:30]}",
                    "detail": "",
                    "data": etat,
                }
            )
            continue
        precedent = None
        rang = presents.index(etat)
        if rang:
            precedent = presents[rang - 1]
        diff = quality.compare(precedent, etat) if precedent else None
        # Le précédent voyage avec la ligne : le panneau en a besoin pour
        # écrire « 171 (−43) », et le recalculer là-bas ferait deux
        # sources pour la même comparaison.
        # La colonne compte les pertes INEXPLIQUÉES : afficher 81 quand
        # 79 sont des refontes voulues par Odoo ferait fuir le lecteur du
        # seul chiffre qui demande une réponse.
        perdu = (
            0
            if diff is None or diff.get("unavailable")
            else len([item for item in diff["rows_lost"] if not item[3]])
        )
        lst.append(
            {
                "kind": "step",
                "label": f"{etat['odoo']:<6} {etat['database'][:24]}",
                "detail": str(perdu) if perdu else "",
                "data": etat,
                "diff": diff,
                "previous": precedent,
            }
        )
    if len(presents) >= 2:
        lst.append(
            {
                "kind": "overall",
                "label": f"🏁 {presents[0]['odoo']} → {presents[-1]['odoo']}",
                "detail": "",
                "data": None,
                "diff": quality.overall(lst_snapshot),
            }
        )
    lst.extend(extra_rows(presents, dct))
    return lst


def extra_rows(presents, dct=None):
    """Les trois sections sous les paliers : succès, validation, revue.

    Elles vivent dans la MÊME table que les paliers plutôt que dans un
    second panneau : on descend la colonne une seule fois, et l'ordre dit
    la démarche — ce que la migration a rendu, où le lire, quoi vérifier
    ensuite.

    Un séparateur n'est PAS sélectionnable au sens où il n'affiche qu'un
    titre ; le laisser dans la liste garde l'index de la table aligné sur
    celui des lignes, ce qu'une liste filtrée perdrait.
    """
    dct = quality.read_progression() if dct is None else dct
    cible = presents[-1]["database"] if presents else ""
    lst = []

    # ── Succès ──
    evenements = quality.read_events(dct)
    ratés = quality.failures(evenements)
    lst.append(
        {
            "kind": "header",
            "label": f"── {t('Verdicts')} ──",
            "detail": str(len(ratés)) if ratés else "✅",
        }
    )
    if not evenements:
        lst.append(
            {
                "kind": "verdict-none",
                "label": f"   {t('no verdict recorded')}",
                "detail": "",
            }
        )
    for event in ratés:
        base = quality.event_database(event)
        # Le PALIER dans le libellé : « smoke_public_url » quatre fois de
        # suite ne dit pas lequel a échoué, et c'est la seule chose qu'on
        # veut savoir en parcourant la colonne.
        palier = quality.event_step(event, base)
        lst.append(
            {
                "kind": "verdict",
                "label": f"   ❌ {palier:<5} {event['name'][:18]}",
                "detail": "▶",
                "event": event,
                "database": base or cible,
                "command": rerun_command(event, base or cible),
            }
        )
    if evenements and not ratés:
        lst.append(
            {
                "kind": "verdict-ok",
                "label": f"   ✅ {len(evenements)} {t('checks, all passed')}",
                "detail": "",
            }
        )

    # ── Validation ──
    lst.append(
        {"kind": "header", "label": f"── {t('Validation')} ──", "detail": ""}
    )
    for role, chemin, existe, _quoi in quality.log_sources():
        lst.append(
            {
                "kind": "source",
                "label": f"   {'📄' if existe else '∅'} {role[:24]}",
                "detail": "",
                "path": chemin,
            }
        )
    lst.append(
        {
            "kind": "logscan",
            "label": f"   🔎 {t('errors in the log')}",
            "detail": "",
        }
    )

    # ── Revue ──
    lst.append(
        {"kind": "header", "label": f"── {t('Review')} ──", "detail": ""}
    )
    for rang, (question, commande, clef) in enumerate(quality.REVUE, 1):
        lst.append(
            {
                "kind": "review",
                "label": f"   {rang}. {t(question)[:26]}",
                "detail": "▶" if clef else "",
                "question": question,
                "command": (
                    commande.format(db=cible)
                    if clef and (cible or "{db}" not in commande)
                    else ""
                ),
            }
        )
    return lst


def rerun_command(event, database):
    """La commande qui rejoue ce verdict, ou "" si on ne sait pas la refaire.

    On la RECONSTRUIT depuis le nom de l'outil plutôt que de rejouer le
    `detail` tel quel : celui-ci porte le chemin d'un venv de palier, qui
    n'est plus celui du checkout courant.
    """
    if not database:
        return ""
    outils = {
        "smoke_public_url": "script/odoo/migration/smoke_public_url.py",
        "database_cleanup": "script/odoo/migration/database_cleanup.py",
        "check_hidden_models": "script/odoo/migration/check_hidden_models.py",
    }
    chemin = outils.get(event.get("name", ""))
    if not chemin:
        return ""
    return f"{chemin} -d {database}"


def head_text(lst_snapshot):
    presents = [x for x in lst_snapshot if x.get("exists")]
    manquants = len(lst_snapshot) - len(presents)
    if not presents:
        return t("No migration in progress.")
    return (
        f"{presents[0]['database']}  ·  {len(presents)} {t('steps')}"
        f"  ·  {presents[0]['odoo']} → {presents[-1]['odoo']}"
        + (
            f"  ·  ⚠️ {manquants} {t('database not found')}"
            if manquants
            else ""
        )
    )


def statistics(etat, precedent):
    """[(libellé, valeur, écart)] pour un palier. L'écart est None au départ.

    Un chiffre seul ne dit rien : 2283 vues est un nombre, « +61 » est une
    information. Le premier palier n'a pas de précédent, et inventer un
    écart de zéro y laisserait croire à une comparaison qui n'existe pas.
    """
    lst = [
        (
            t("modules"),
            len(etat["installed"]),
            None if not precedent else len(precedent["installed"]),
        ),
        (
            t("models"),
            len(etat["model"]),
            None if not precedent else len(precedent["model"]),
        ),
        (
            t("views"),
            etat["view"],
            None if not precedent else precedent["view"],
        ),
        (
            "  · COW",
            etat["view_cow"],
            None if not precedent else precedent["view_cow"],
        ),
        (
            t("menus"),
            etat["menu"],
            None if not precedent else precedent["menu"],
        ),
        (
            t("attachments"),
            etat["attachment"],
            None if not precedent else precedent["attachment"],
        ),
    ]
    return [
        (libelle, valeur, None if avant is None else valeur - avant)
        for libelle, valeur, avant in lst
    ]


EXTRA_KINDS = (
    "header",
    "verdict",
    "verdict-none",
    "verdict-ok",
    "source",
    "logscan",
    "review",
)


def extra_pane(row, colour=False):
    """Le panneau des trois sections ajoutées sous les paliers."""
    genre = row["kind"]
    if genre == "header":
        return t("Pick a line below.")
    if genre == "verdict":
        return verdict_pane(row, colour)
    if genre == "verdict-none":
        return "\n".join(
            [
                t("The migration recorded no verdict."),
                "",
                t("Verdicts live in lst_event of the progression file,"),
                t("not in command_executed, which only lists what ran."),
            ]
        )
    if genre == "verdict-ok":
        return t("Every recorded check returned zero.")
    if genre == "source":
        return source_pane(row, colour)
    if genre == "logscan":
        return logscan_pane(colour)
    if genre == "review":
        return review_pane(row, colour)
    return ""


def verdict_pane(row, colour=False):
    """Ce qu'un verdict raté dit, et ce que son code de retour signifie."""
    event = row.get("event") or {}
    lignes = [
        status.paint(f"❌ {event.get('name')}", "fail", colour),
        "",
        # Le palier est la version d'ODOO, pas le compteur du pilote :
        # « 4.1.I » désigne la première étape du quatrième bloc, et la
        # migration en est alors au palier 14. Les afficher tous deux sous
        # le même mot faisait lire « palier 4.1 », qui n'existe pas.
        f"   {t('step'):<10} {quality.event_step(event)}"
        f"   ({event.get('step')})",
        f"   {t('when'):<10} {event.get('at')[:19]}",
        f"   {t('status'):<10} {event.get('status')}",
        "",
        f"   {t('what it ran')}",
        f"      {event.get('detail', '')[:150]}",
        "",
    ]
    sens = {
        "smoke_public_url": t(
            "1 means a public page failed — not merely a finding."
        ),
        "database_cleanup": t(
            "1 means leftovers remain that it could not drop."
        ),
    }.get(event.get("name"), "")
    if sens:
        lignes.append(f"   {sens}")
        lignes.append("")
    if row.get("command"):
        lignes.append(
            status.paint(
                f"   ▶ {t('press r to run it again')}", "step", colour
            )
        )
        lignes.append(f"      {row['command']}")
        lignes.append("")
        lignes.append(
            f"   {t('The screen steps aside, the test takes the terminal,')}"
        )
        lignes.append(f"   {t('and you come back with Enter.')}")
    else:
        lignes.append(f"   {t('No known way to replay this one.')}")
    return "\n".join(lignes)


def source_pane(row, colour=False):
    """Où la migration laisse ses traces, et ce que chacune contient."""
    lignes = [status.paint(t("Where the traces live"), "step", colour), ""]
    for role, chemin, existe, quoi in quality.log_sources():
        marque = "📄" if existe else "∅"
        teinte = "ok" if existe else "warn"
        lignes.append(f"   {marque} {status.paint(role, teinte, colour)}")
        lignes.append(f"      {chemin}")
        lignes.append(f"      {quoi}")
        if not existe:
            lignes.append(f"      {t('missing: nothing was written here')}")
        lignes.append("")
    lignes.append(f"   {t('To read the verdicts by hand:')}")
    lignes.append("      python3 - <<'PY'")
    lignes.append("      import json, io")
    lignes.append(
        "      d = json.load(io.open("
        f"'{quality.DEFAULT_PROGRESSION}', encoding='utf-8'))"
    )
    lignes.append("      for e in d['lst_event']:")
    lignes.append("          if e.get('status'):")
    lignes.append("              print(e['step'], e['name'], e['status'])")
    lignes.append("      PY")
    return "\n".join(lignes)


def logscan_pane(colour=False):
    """Les erreurs du journal d'Odoo — ou pourquoi il n'y en a pas."""
    rapport = quality.scan_log()
    lignes = [status.paint(t("Errors in the Odoo log"), "step", colour), ""]
    lignes.append(f"   {rapport['path']}")
    if not rapport["exists"]:
        lignes.append("")
        lignes.append(
            status.paint(
                f"   ∅ {t('This file does not exist.')}", "warn", colour
            )
        )
        lignes.append("")
        lignes.append(
            f"   {t('config.conf has an empty logfile=, so Odoo writes to')}"
        )
        lignes.append(
            f"   {t('the terminal and its output dies with it. To keep it:')}"
        )
        lignes.append("")
        lignes.append(
            f"      logfile = {os.path.abspath(quality.JOURNAL_ODOO)}"
        )
        return "\n".join(lignes)
    lignes.append("")
    for motif, combien in rapport["counts"].items():
        teinte = "fail" if combien else "ok"
        lignes.append(
            f"   {status.paint(motif.ljust(10), teinte, colour)} {combien}"
        )
    if rapport["lines"]:
        lignes.append("")
        lignes.append(f"   {t('last offending lines')}")
        for ligne in rapport["lines"]:
            lignes.append(f"      {ligne}")
    return "\n".join(lignes)


def review_pane(row, colour=False):
    """Une étape de la revue : ce qu'elle prouve, et ce qu'elle ne prouve pas."""
    lignes = [
        status.paint(t(row.get("question", "")), "step", colour),
        "",
    ]
    if row.get("command"):
        lignes.append(f"   {row['command']}")
        lignes.append("")
        lignes.append(
            status.paint(f"   ▶ {t('press r to run it')}", "step", colour)
        )
    else:
        lignes.append(f"   {t('Read it in the Verdicts section above.')}")
    lignes.append("")
    lignes.append(f"   {t('What none of these can see')}")
    lignes.append(
        f"      {t('They all read the DATABASE. A module that kept a')}"
    )
    lignes.append(
        f"      {t('pre-18 view type, or an image URL Odoo no longer')}"
    )
    lignes.append(
        f"      {t('accepts, breaks at runtime on a perfectly sound one.')}"
    )
    return "\n".join(lignes)


def pane_text(lst_snapshot, row, colour=False, mode=None):
    """Le détail du palier choisi, ou le bilan d'ensemble.

    UN seul mode, et non deux drapeaux : « montre les fichiers absents »
    et « montre la liste des modèles » ne peuvent pas être vrais en même
    temps, et deux booléens laissaient écrire cet état impossible.
    """
    if row is None:
        return t("Nothing to show yet.")
    if row["kind"] in EXTRA_KINDS:
        return extra_pane(row, colour)
    if row["kind"] == "missing":
        return f"⚠️  {row['data']['database']} : {t('database not found')}"
    etat = row["data"]
    if mode == "missing":
        if not etat:
            return t("Pick a step to see its missing files.")
        return quality.render_missing(etat, colour)
    if mode in quality.DETAILS:
        return quality.render_detail(row.get("diff"), mode, colour)
    lignes = []
    if etat:
        lignes.append(
            status.paint(f"{etat['odoo']}  {etat['database']}", "step", colour)
        )
        lignes.append("")
        for libelle, valeur, ecart in statistics(etat, row.get("previous")):
            if ecart is None:
                marque = ""
            else:
                marque = status.paint(
                    f"{ecart:+d}", "ok" if ecart >= 0 else "warn", colour
                )
            lignes.append(f"   {libelle:<28} {valeur:>7}   {marque}")
        if etat.get("attachment_missing"):
            lignes.append(
                "   "
                + status.paint(
                    f"❌ {etat['attachment_missing']}"
                    f" {t('attachment files missing from the filestore')}",
                    "fail",
                    colour,
                )
            )
            lignes.append(f"      {t('press m to list them')}")
        lignes.append("")
    diff = row.get("diff")
    if diff:
        lignes.extend(quality.render_compare(diff, colour, limit=40))
    return "\n".join(lignes)


def mode_label(mode):
    """Le nom du mode courant, pour le sous-titre.

    Un panneau qui change de contenu sans dire pourquoi se lit comme un
    écran cassé — et avec sept modes, on ne devine pas.
    """
    if mode is None:
        return t("summary")
    if mode == "missing":
        return t("Missing files")
    return t(mode)


def run_in_terminal(command, wait=True):
    """Rendre le terminal au test, puis le reprendre. (code, a_tourné).

    L'écran DOIT s'effacer : `smoke_public_url` monte une instance Odoo et
    écrit des centaines de lignes ; les capturer les cacherait, et les
    laisser passer par-dessus la TUI la déchirerait. Textual sait se
    retirer — `suspend()` chez l'appelant — et c'est le seul moment où ce
    processus peut lancer autre chose sans se battre pour l'affichage.

    L'attente d'Entrée n'est pas une politesse : sans elle, l'écran se
    reconstruit par-dessus le résultat avant qu'on ait pu le lire.
    """
    if not command:
        return None, False
    argv = command.split()
    if argv[0].endswith(".py"):
        argv = [sys.executable] + argv
    print()
    print(f"▶ {' '.join(argv)}")
    print("─" * 72)
    try:
        code = subprocess.run(argv, cwd=REPO_ROOT).returncode
    except OSError as exc:
        print(f"❌ {exc}")
        code = None
    print("─" * 72)
    print(f"↩ {t('exit code:')} {code}")
    if wait:
        try:
            input(t("Press Enter to go back to the screen…"))
        except (EOFError, KeyboardInterrupt):
            pass
    return code, True


def build_app(lst_snapshot):
    """Textual est importé ICI : le module reste testable sans lui."""
    from rich.text import Text
    from textual.app import App, ComposeResult
    from textual.containers import Horizontal, VerticalScroll
    from textual.widgets import DataTable, Footer, Header, Static

    class QualityApp(App):
        CSS = globals()["CSS"]
        BINDINGS = [
            ("q,escape", "quit", t("Quit")),
            ("m", "toggle_missing", t("Missing files")),
            ("d", "cycle_detail", t("Details")),
            ("r,enter", "run_selected", t("Run")),
        ]

        def __init__(self, lst_snapshot):
            super().__init__()
            self.lst_snapshot = lst_snapshot
            self.lst_row = rows(lst_snapshot)
            self.index = 0
            self.mode = None

        def compose(self) -> ComposeResult:
            yield Header()
            yield Static("", id="head")
            with Horizontal(id="body"):
                yield DataTable(id="left", cursor_type="row")
                with VerticalScroll(id="pane"):
                    yield Static("", id="content")
            yield Footer()

        def on_mount(self):
            self.title = t("Migration quality, step by step")
            table = self.query_one("#left", DataTable)
            table.add_columns(t("steps"), "▼")
            for row in self.lst_row:
                table.add_row(row["label"][:34], row["detail"])
            self.query_one("#head", Static).update(
                head_text(self.lst_snapshot)
            )
            self._show()

        def _show(self):
            self.sub_title = mode_label(self.mode)
            row = (
                self.lst_row[self.index]
                if self.lst_row and self.index < len(self.lst_row)
                else None
            )
            self.query_one("#content", Static).update(
                Text.from_ansi(
                    pane_text(
                        self.lst_snapshot,
                        row,
                        colour=True,
                        mode=self.mode,
                    )
                )
            )

        def action_toggle_missing(self):
            """Basculer entre les chiffres du palier et ses fichiers absents.

            Les métadonnées ne sont lues qu'ICI : une requête de plus par
            base allongerait un parcours qui tient en quatre secondes, pour
            une information qu'on ne regarde qu'en la demandant.
            """
            self.mode = None if self.mode == "missing" else "missing"
            self._show()

        def action_cycle_detail(self):
            """Parcourir les listes ENTIÈRES, une catégorie à la fois.

            Le résumé coupe à huit entrées et il a raison ; mais quand on
            cherche si UN module précis a survécu, la liste tronquée ne
            répond pas. On enchaîne donc résumé → modules → modèles →
            champs → copies COW → tables, et l'on revient.
            """
            suite = (None,) + quality.DETAILS
            courant = self.mode if self.mode in suite else None
            self.mode = suite[(suite.index(courant) + 1) % len(suite)]
            self._show()

        def action_run_selected(self):
            """Rejouer le test de la ligne choisie, hors de l'écran.

            `suspend()` rend le terminal pour de bon : le test peut monter
            son instance Odoo et écrire ce qu'il veut. Rien n'est capturé,
            donc rien n'est caché.
            """
            row = (
                self.lst_row[self.index]
                if self.lst_row and self.index < len(self.lst_row)
                else None
            )
            commande = row.get("command") if row else ""
            if not commande:
                # Une ligne sans commande n'est pas une erreur : la plupart
                # n'en ont pas. Un bip dit « rien ici » sans interrompre.
                self.bell()
                return
            with self.suspend():
                run_in_terminal(commande)
            self.refresh()

        def on_data_table_row_highlighted(self, event):
            if event.data_table.id == "left" and self.lst_row:
                self.index = event.cursor_row
                self._show()

    return QualityApp(lst_snapshot)


def run_tui(lst_snapshot, run_app=True):
    """Ouvrir l'écran. False si l'on n'a pas pu — et alors on DIT pourquoi."""
    if not lst_snapshot:
        return False
    if not sys.stdout.isatty():
        print(f"ℹ️  {t('Not a terminal: showing the text report instead.')}")
        return False
    try:
        from script.todo import textual_setup
    except Exception:
        textual_setup = None
    if textual_setup and not textual_setup.ensure():
        return False
    try:
        app = build_app(lst_snapshot)
    except ImportError:
        print(
            f"ℹ️  {t('Textual is missing from this interpreter:')}"
            f" {sys.executable}"
        )
        return False
    if not run_app:
        return app
    if in_event_loop():
        # Filet de sécurité : `app.run()` appelle `asyncio.run()`, qui
        # lève dans une boucle déjà en cours. Le dire vaut mieux que la
        # trace de quarante lignes que cela produit — et l'appelant doit
        # passer par un sous-processus.
        print(
            f"ℹ️  {t('Already inside a running screen: open it in its own')}"
            f" {t('process instead.')}"
        )
        return False
    app.run()
    return True


def in_event_loop():
    """Une boucle asyncio tourne-t-elle déjà dans CE processus ?"""
    import asyncio

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return False
    return True
