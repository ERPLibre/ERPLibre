#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""L'écran Textual de l'installateur ERPLibre (python-textual du dépôt
extra d'Arch, embarqué dans l'ISO).

Écrans, dans l'ordre d'une installation :

  HomeScreen     [1] installer, [2] TODO, [3] archinstall guidé ;
  FormScreen     clavier d'abord (loadkeys appliqué dès qu'on quitte le
                 champ), puis les champs de erplibre_ui_flow.form_fields ;
  RecapScreen    plan résolu, matériel, disque EFFACÉ, commandes, et le
                 nom du disque à retaper ;
  ProgressScreen sortie du cœur et journal de l'étape ERPLibre ;
  FinalScreen    redémarrer, shell ou accueil.

Aucune décision ici : chaque champ, chaque vérification, le document de
réponses et le lancement du cœur viennent de erplibre_ui_flow, que le
mode texte partage. L'application rend (action, donnée, tr) par
App.exit() quand le lanceur doit prendre le terminal : « todo »,
« archinstall », « reboot », « shell ».

`run`, `popen` et `sleep` sont injectés : les tests pilotent l'écran
par App.run_test() sans lancer loadkeys, getent ni le cœur.
"""

import subprocess
import time

import erplibre_ui_flow as flow
from textual import work
from textual.app import App
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.content import Content
from textual.screen import Screen
from textual.suggester import SuggestFromList
from textual.widgets import (
    Button,
    Checkbox,
    Input,
    Log,
    Select,
    Static,
)

# Bordures en traits simples (┌─┐) : la police de la console Linux les a,
# alors que les demi-blocs des bordures « tall » et « round » de Textual
# s'y affichent en blancs ou en « # ».
CSS = """
Screen { background: $surface; }
#title { text-style: bold; padding: 0 1; background: $primary; color: $text; }
.info { padding: 0 1; }
.box { border: solid $primary; padding: 0 1; height: auto; }
.field { height: auto; margin: 0 0 1 0; }
.error { color: $error; padding: 0 1; }
.warn { color: $warning; }
.danger { color: $error; text-style: bold; padding: 0 1; }
#buttons { height: auto; padding: 0 1; }
#buttons Button { margin: 0 1 0 0; }
#home-buttons { height: auto; padding: 1 1; }
#home-buttons Button { width: 100%; margin: 0 0 1 0; }
#log { height: 1fr; border: solid $primary; }
Input, Select { width: 100%; }
Input { border: solid $panel-lighten-2; }
Input:focus { border: solid $accent; }
SelectCurrent { border: solid $panel-lighten-2; }
Select:focus > SelectCurrent { border: solid $accent; }
Button { border: solid $panel-lighten-2; }
Button:focus { border: solid $accent; }
"""


class Text(Static):
    """Un Static sans balisage Rich : les textes affichés portent des
    crochets (« < [luks] », un modèle de disque) que Rich prendrait pour
    des balises."""

    def __init__(self, *args, **kwargs):
        kwargs.setdefault("markup", False)
        super().__init__(*args, **kwargs)


# Lignes gardées à l'écran : archinstall en écrit des milliers, le journal
# complet reste dans /var/log/erplibre-install et /var/log/archinstall.
LOG_MAX_LINES = 5000


def safe_id(cle):
    """Un identifiant de widget tiré d'une clé de champ (les points des
    chemins du profil n'y sont pas permis)."""
    return cle.replace(".", "-")


def select_value(widget):
    """La valeur d'un Select, ou None quand rien n'est choisi."""
    valeur = widget.value
    if valeur is Select.BLANK or valeur is Select.NULL:
        return None
    return valeur


class InstallerApp(App):
    """L'application entière ; HomeScreen s'ouvre au montage."""

    CSS = CSS
    TITLE = "ERPLibre"
    # La palette de commandes (Ctrl+P) a sa propre commande « Quit », qui
    # appelle action_quit sans passer par les liaisons ci-dessous : elle
    # fermerait l'écran au milieu de l'effacement du disque, le cœur
    # continuant sans personne pour lire sa sortie.
    ENABLE_COMMAND_PALETTE = False
    BINDINGS = [
        Binding("ctrl+q", "quit_shell", "Shell", show=False, priority=True),
        Binding("ctrl+c", "quit_shell", "Shell", show=False, priority=True),
    ]

    def __init__(
        self,
        ctx,
        tr,
        run=subprocess.run,
        popen=subprocess.Popen,
        sleep=time.sleep,
        dry_run=False,
    ):
        super().__init__()
        self.ctx = ctx
        self.tr = tr
        self.run_cmd = run
        self.popen = popen
        self.sleep = sleep
        self.dry_run = dry_run
        # Vrai pendant que le cœur tourne : quitter le laisserait orphelin
        # au milieu de l'effacement du disque.
        self.busy = False

    def on_mount(self):
        self.push_screen(HomeScreen())

    def finish(self, action, donnee=None):
        self.exit((action, donnee, self.tr))

    def action_quit_shell(self):
        if self.busy:
            self.notify(self.tr("The installation is running."))
            return
        self.finish("shell")

    async def action_quit(self):
        # Tout autre chemin vers la sortie de Textual passe par ici : il
        # obéit à la même garde que Ctrl+Q.
        self.action_quit_shell()

    def return_home(self):
        while not isinstance(self.screen, HomeScreen):
            self.pop_screen()


class HomeScreen(Screen):
    BINDINGS = [
        Binding("1", "install", show=False),
        Binding("2", "todo", show=False),
        Binding("3", "archinstall", show=False),
        Binding("l", "lang", show=False),
        Binding("r", "reboot", show=False),
        Binding("q", "shell", show=False),
    ]

    def compose(self):
        tr = self.app.tr
        yield Text(
            tr("ERPLibre installer — Arch Linux + GNOME + ERPLibre"),
            id="title",
        )
        yield Text(self.profile_text(), id="profile", classes="info")
        yield Text(tr("Network: checking…"), id="status", classes="info")
        with Vertical(id="home-buttons"):
            yield Button(f"1  {tr('Install ERPLibre')}", id="install")
            yield Button(f"2  {tr('Start ERPLibre TODO')}", id="todo")
            yield Button(
                f"3  {tr('Run archinstall (guided, pre-filled)')}",
                id="archinstall",
            )
        with Horizontal(id="buttons"):
            yield Button(f"L  {tr('Français / English')}", id="lang")
            yield Button(f"R  {tr('Reboot')}", id="reboot")
            yield Button(f"Q  {tr('Quit to the shell')}", id="shell")

    def on_mount(self):
        self.check_status()
        self.set_interval(10, self.check_status)

    def profile_text(self):
        ctx, tr = self.app.ctx, self.app.tr
        if ctx.get("profile_error"):
            code, details = ctx["profile_error"]
            return flow.reason_message(tr, code, details)
        return tr(
            "Machine profile: {profile}", profile=flow.profile_title(ctx, tr)
        )

    @work(thread=True, exclusive=True, group="status")
    def check_status(self):
        etat = flow.live_status(self.app.run_cmd)
        self.app.call_from_thread(self.show_status, etat)

    def show_status(self, etat):
        tr = self.app.tr
        texte = tr(
            "Network: {state}",
            state=tr("connected") if etat["network"] else tr("NOT connected"),
        )
        if not etat["network"]:
            texte += "  " + tr("(cable, or « iwctl » from the shell)")
        try:
            self.query_one("#status", Static).update(texte)
        except Exception:
            pass

    async def on_button_pressed(self, event):
        resultat = getattr(self, f"action_{event.button.id}")()
        if resultat is not None:
            await resultat

    def action_install(self):
        if not self.app.ctx.get("profile"):
            self.app.notify(self.profile_text(), severity="error")
            return
        self.app.push_screen(FormScreen())

    def action_todo(self):
        self.app.finish("todo")

    def action_archinstall(self):
        self.app.push_screen(ArchinstallScreen())

    async def action_lang(self):
        self.app.tr = self.app.tr.toggled()
        self.app.ctx["lang"] = self.app.tr.lang
        await self.recompose()
        self.check_status()

    def action_reboot(self):
        self.app.finish("reboot")

    def action_shell(self):
        self.app.finish("shell")


class FormScreen(Screen):
    """Le formulaire : un bloc par champ (libellé, widget, erreur),
    montré ou caché selon flow.visible()."""

    BINDINGS = [
        Binding("escape", "back", show=False),
        Binding("f10", "next", show=False),
    ]

    def __init__(self):
        super().__init__()
        self.fields = []
        self.applied_keymap = None

    def compose(self):
        ctx, tr = self.app.ctx, self.app.tr
        self.fields = flow.form_fields(ctx, tr)
        yield Text(tr("Install ERPLibre"), id="title")
        yield Text(
            tr(
                "Machine profile: {profile}",
                profile=flow.profile_title(ctx, tr),
            ),
            classes="info",
        )
        yield Text(
            tr("Tab: next field — F10: next screen — Esc: back"),
            classes="info",
        )
        yield Text("", id="messages", classes="error")
        with VerticalScroll(id="form"):
            for champ in self.fields:
                with Vertical(
                    classes="field", id=f"f-{safe_id(champ['key'])}"
                ):
                    if champ["kind"] != "bool":
                        yield Text(champ["label"], classes="info")
                    yield self.widget(champ)
                    yield Text(
                        "", classes="error", id=f"e-{safe_id(champ['key'])}"
                    )
        with Horizontal(id="buttons"):
            yield Button(tr("Back"), id="back")
            yield Button(tr("Next"), id="next", variant="primary")

    def widget(self, champ):
        wid = f"w-{safe_id(champ['key'])}"
        sorte = champ["kind"]
        defaut = champ.get("default")
        if sorte in ("secret", "confirm"):
            return Input(password=True, id=wid)
        if sorte == "bool":
            return Checkbox(champ["label"], value=bool(defaut), id=wid)
        if sorte == "choice":
            # Sans défaut, la valeur est Select.NULL (« rien de choisi ») :
            # Select.BLANK vaut False dans textual 8 et n'est pas une
            # valeur, le Select lèverait InvalidSelectValueError au montage.
            return Select(
                [
                    (Content(libelle), valeur)
                    for valeur, libelle in champ["choices"]
                ],
                value=defaut if defaut is not None else Select.NULL,
                allow_blank=defaut is None,
                id=wid,
            )
        suggestions = champ.get("choices") or []
        return Input(
            value=str(defaut or ""),
            suggester=SuggestFromList(suggestions, case_sensitive=False)
            if suggestions
            else None,
            id=wid,
        )

    def on_mount(self):
        self.refresh_visibility()
        # Le clavier d'abord : sans focus posé, la première frappe ne va à
        # aucun champ.
        self.query_one("#w-keymap", Input).focus()
        clavier = self.values().get("keymap")
        if clavier:
            self.apply_keymap(clavier)

    def values(self):
        valeurs = {}
        for champ in self.fields:
            w = self.query_one(f"#w-{safe_id(champ['key'])}")
            if isinstance(w, Select):
                valeurs[champ["key"]] = select_value(w)
            elif isinstance(w, Checkbox):
                valeurs[champ["key"]] = w.value
            else:
                valeurs[champ["key"]] = w.value
        return valeurs

    def refresh_visibility(self):
        montres = flow.visible(self.app.ctx, self.values())
        for champ in self.fields:
            bloc = self.query_one(f"#f-{safe_id(champ['key'])}")
            bloc.display = champ["key"] in montres

    def on_select_changed(self, _event):
        self.refresh_visibility()

    def on_checkbox_changed(self, _event):
        self.refresh_visibility()

    def on_input_submitted(self, event):
        if event.input.id == "w-keymap":
            self.apply_keymap(event.value)
        self.focus_next()

    def on_descendant_blur(self, event):
        if getattr(event.widget, "id", None) == "w-keymap":
            self.apply_keymap(event.widget.value)

    def apply_keymap(self, nom):
        """loadkeys dès que le clavier change : les phrases LUKS qui
        suivent se tapent avec la disposition qu'aura la console."""
        nom = (nom or "").strip()
        if nom == self.applied_keymap:
            return
        refus = flow.check_keymap(
            nom, self.app.ctx.get("keymaps"), self.app.tr
        )
        if refus:
            self.query_one("#e-keymap", Static).update(refus)
            return
        self.applied_keymap = nom
        self.run_loadkeys(nom)

    @work(thread=True, exclusive=True, group="keymap")
    def run_loadkeys(self, nom):
        ok, erreur = flow.apply_keymap(nom, self.app.run_cmd)
        tr = self.app.tr
        message = (
            tr("Keyboard layout « {name} » applied.", name=nom)
            if ok
            else tr("loadkeys {name} failed: {error}", name=nom, error=erreur)
        )
        self.app.call_from_thread(self.show_keymap, ok, message)

    def show_keymap(self, ok, message):
        self.query_one("#e-keymap", Static).update("" if ok else message)
        if ok:
            self.app.notify(message)

    def on_button_pressed(self, event):
        if event.button.id == "back":
            self.action_back()
        elif event.button.id == "next":
            self.action_next()

    def action_back(self):
        self.app.pop_screen()

    def action_next(self):
        ctx, tr = self.app.ctx, self.app.tr
        valeurs = self.values()
        self.apply_keymap(valeurs.get("keymap"))
        for champ in self.fields:
            self.query_one(f"#e-{safe_id(champ['key'])}", Static).update("")
        messages = self.query_one("#messages", Static)
        messages.update("")
        doc, erreurs = flow.collect(ctx, valeurs, tr)
        if erreurs:
            for cle, message in erreurs:
                self.query_one(f"#e-{safe_id(cle)}", Static).update(message)
            self.query_one(f"#w-{safe_id(erreurs[0][0])}").focus()
            messages.update(tr("Some answers need fixing."))
            return
        avis = flow.review(ctx, doc, tr)
        if not avis["ok"]:
            messages.update("\n".join(avis["messages"]))
            return
        self.app.push_screen(RecapScreen(doc, avis["prep"]))


class RecapScreen(Screen):
    BINDINGS = [Binding("escape", "back", show=False)]

    def __init__(self, doc, prep):
        super().__init__()
        self.doc = doc
        self.prep = prep

    def compose(self):
        ctx, tr = self.app.ctx, self.app.tr
        vue = flow.recap(ctx, self.doc, self.prep, tr)
        self.view = vue
        yield Text(tr("Summary — nothing is written yet"), id="title")
        with VerticalScroll():
            yield Text(
                tr("Machine profile: {profile}", profile=vue["profile"]),
                classes="info",
            )
            yield Text(self.summary_text(), id="summary", classes="box")
            yield Text(
                tr("Hardware")
                + "\n"
                + "\n".join(f"{a} : {b}" for a, b in vue["hardware"]),
                classes="box",
            )
            avis = Text(
                self.warnings_text(), id="warnings", classes="box warn"
            )
            avis.display = bool(vue["warnings"])
            yield avis
            yield Text(self.commands_text(), id="commands", classes="box")
            yield Text(
                tr("ALL DATA ON THIS DISK WILL BE ERASED:")
                + "\n  "
                + vue["disk"]
                + "".join(f"\n    {p}" for p in vue["partitions"]),
                classes="danger",
            )
            if vue["nvme_lbaf"] is not None:
                yield Checkbox(
                    tr(
                        "Reformat the NVMe disk to 4 KiB sectors "
                        "(format {lbaf})?",
                        lbaf=vue["nvme_lbaf"],
                    ),
                    value=False,
                    id="nvme",
                )
            yield Text(
                tr("Type « {name} » to erase it:", name=vue["expected"]),
                classes="info",
            )
            yield Input(placeholder=vue["expected"] or "", id="confirm")
            yield Text("", id="confirm-error", classes="error")
        with Horizontal(id="buttons"):
            yield Button(tr("Back"), id="back")
            yield Button(
                tr("Erase and install"), id="install", variant="error"
            )

    def summary_text(self):
        return "\n".join(f"{a} : {b}" for a, b in self.view["summary"])

    def warnings_text(self):
        return "\n".join(f"! {a}" for a in self.view["warnings"])

    def commands_text(self):
        return (
            self.app.tr("Commands") + "\n" + "\n".join(self.view["commands"])
        )

    def on_mount(self):
        self.query_one("#confirm", Input).focus()

    def on_checkbox_changed(self, event):
        """La case NVMe change le plan : la commande « nvme format » et la
        taille de secteur LUKS (4096) s'affichent dès qu'elle est cochée,
        avant que le nom du disque ne soit retapé."""
        if event.checkbox.id != "nvme":
            return
        ctx, tr = self.app.ctx, self.app.tr
        avis = flow.review(
            ctx, flow.with_nvme_format(self.doc, event.value), tr
        )
        if not avis["ok"]:
            return
        self.prep = avis["prep"]
        self.view = flow.recap(ctx, self.doc, self.prep, tr)
        self.query_one("#summary", Static).update(self.summary_text())
        self.query_one("#commands", Static).update(self.commands_text())
        avertissements = self.query_one("#warnings", Static)
        avertissements.update(self.warnings_text())
        avertissements.display = bool(self.view["warnings"])

    def on_input_submitted(self, _event):
        self.action_install()

    def on_button_pressed(self, event):
        if event.button.id == "back":
            self.action_back()
        elif event.button.id == "install":
            self.action_install()

    def action_back(self):
        self.app.pop_screen()

    def action_install(self):
        tr = self.app.tr
        tape = self.query_one("#confirm", Input).value.strip()
        if not flow.disk_confirmed(self.prep, tape):
            self.query_one("#confirm-error", Static).update(
                tr(
                    "Type exactly « {name} » to confirm.",
                    name=self.view["expected"],
                )
            )
            return
        nvme = False
        if self.view["nvme_lbaf"] is not None:
            nvme = self.query_one("#nvme", Checkbox).value
        doc = flow.confirm_document(self.doc, tape, nvme, self.prep)
        self.app.push_screen(ProgressScreen(doc))


class ProgressScreen(Screen):
    """La sortie du cœur, puis celle de l'étape ERPLibre relue dans la
    cible. Ni retour ni sortie tant que le cœur tourne."""

    def __init__(self, doc):
        super().__init__()
        self.doc = doc
        self.tail = None

    def compose(self):
        tr = self.app.tr
        yield Text(
            tr("Installation in progress — do not power off"), id="title"
        )
        yield Log(id="log", highlight=False, max_lines=LOG_MAX_LINES)
        yield Text(
            tr("Logs: {path}", path="/var/log/erplibre-install"),
            classes="info",
        )

    def on_mount(self):
        self.app.busy = True
        self.tail = flow.StageLogTail(flow.stage_log_path(self.app.ctx))
        self.set_interval(1, self.poll_stage)
        self.install()

    def add_line(self, ligne):
        self.query_one("#log", Log).write_line(ligne)

    def poll_stage(self):
        for ligne in self.tail.poll():
            self.add_line("[stage] " + ligne)

    @work(thread=True, exclusive=True, group="install")
    def install(self):
        app = self.app

        def log(ligne):
            app.call_from_thread(self.add_line, ligne)

        attente = {"run": app.run_cmd, "sleep": app.sleep}
        if not app.dry_run and not flow.wait_ready(log, app.tr, **attente):
            rc = flow.NETWORK_EXIT
        else:
            rc = flow.run_core(
                app.ctx, self.doc, log, popen=app.popen, dry_run=app.dry_run
            )
        app.call_from_thread(self.done, rc)

    def done(self, rc):
        self.poll_stage()
        # Le document porte les secrets : il ne survit pas à l'installation.
        self.doc = None
        self.app.busy = False
        self.app.push_screen(FinalScreen(rc))


class FinalScreen(Screen):
    BINDINGS = [
        Binding("r", "reboot", show=False),
        Binding("q", "shell", show=False),
        Binding("h", "home", show=False),
    ]

    def __init__(self, rc):
        super().__init__()
        self.rc = rc

    def compose(self):
        tr = self.app.tr
        yield Text(
            tr("Installation finished")
            if self.rc == 0
            else tr("Installation failed"),
            id="title",
        )
        yield Text(
            flow.exit_message(tr, self.rc, self.app.dry_run),
            classes="info" if self.rc == 0 else "danger",
            id="verdict",
        )
        yield Text(
            tr("Exit code: {rc}", rc=self.rc)
            + "\n"
            + tr("Logs: {path}", path="/var/log/erplibre-install"),
            classes="info",
        )
        with Horizontal(id="buttons"):
            yield Button(tr("Reboot"), id="reboot", variant="primary")
            yield Button(tr("Quit to the shell"), id="shell")
            yield Button(tr("Back to the home screen"), id="home")

    def on_button_pressed(self, event):
        getattr(self, f"action_{event.button.id}")()

    def action_reboot(self):
        self.app.finish("reboot")

    def action_shell(self):
        self.app.finish("shell")

    def action_home(self):
        self.app.return_home()


class ArchinstallScreen(Screen):
    """[3] : le profil ERPLibre à pré-remplir, puis archinstall guidé
    (lancé par le lanceur, hors de l'écran)."""

    BINDINGS = [Binding("escape", "back", show=False)]

    def compose(self):
        ctx, tr = self.app.ctx, self.app.tr
        yield Text(tr("Run archinstall (guided, pre-filled)"), id="title")
        yield Text(
            tr(
                "archinstall asks the disk, an account (required for "
                "ERPLibre), the language and the time zone. The network "
                "is required."
            ),
            classes="info",
        )
        yield Text(tr("What should be installed with GNOME?"), classes="info")
        yield Select(
            [
                (Content(e["label"]), e["key"])
                for e in ctx.get("erplibre") or []
            ],
            value=flow._default_erplibre(ctx) or Select.NULL,
            allow_blank=not ctx.get("erplibre"),
            id="erplibre",
        )
        with Horizontal(id="buttons"):
            yield Button(tr("Back"), id="back")
            yield Button(
                tr("Start archinstall"), id="start", variant="primary"
            )

    def on_button_pressed(self, event):
        if event.button.id == "back":
            self.action_back()
        elif event.button.id == "start":
            cle = select_value(self.query_one("#erplibre", Select))
            if cle:
                self.app.finish("archinstall", cle)
            else:
                self.app.notify(
                    self.app.tr("No ERPLibre profile on this key."),
                    severity="error",
                )

    def action_back(self):
        self.app.pop_screen()


def session(ctx, tr, **options):
    """Lance l'application ; rend (action, donnée, tr), « shell » si elle
    se ferme sans action."""
    resultat = InstallerApp(ctx, tr, **options).run()
    return resultat or ("shell", None, tr)
