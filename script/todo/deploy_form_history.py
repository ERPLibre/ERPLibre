#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""L'historique des modifications d'un formulaire de déploiement.

Un geste de masse — F6 coche tout le catalogue, et F6 voisine F5 — change le
plan d'un coup, sans rien annoncer ni rien permettre de défaire. L'historique
garde un INSTANTANÉ de l'état logique du formulaire après chaque modification
stable, et y revient : ctrl+z recule d'un pas, ctrl+y avance, « h » ou F2
liste les états et Entrée saute à l'un d'eux.

Un instantané est un dict de l'état LOGIQUE — attributs du modèle, cases du
catalogue par identité, valeur de chaque champ de la colonne de gauche —,
jamais un arbre de widgets. Les rangées du plan s'en déduisent et sont
reconstruites. Deux instantanés se comparent par « == » : un message qui ne
change rien, comme l'écho d'un montage, ne crée pas d'entrée.

L'historique ne perd rien. Revenir en arrière déplace seulement le curseur ;
si une modification suit, une entrée « retour à … » rejoue d'abord l'état
quitté, puis la modification s'ajoute après. Les états qu'on avait sautés
restent dans la liste, au-dessus.

* History, describe, label_for : fonctions pures, sans Textual ;
* HistoryMixin : branchement dans un formulaire Textual ;
* history_screen() : la liste, construite au premier appel.

Ce que le formulaire hôte fournit, en plus du contrat de PlanMixin :

* `_hist_model_attrs()`      les attributs du modèle à garder ;
* `_hist_catalog()`          les identités cochées du catalogue ;
* `_hist_restore_catalog(s)` recoche le catalogue d'un instantané ;
* `_hist_restore_radios(s)`  presse les boutons tenus par le modèle ;
* `_hist_sync_derived(s)`    remet ce qui découle des champs (grisés,
  champs révélés) ;
* `_hist_rebuild()`          reconstruit le plan depuis le modèle ;
* `_hist_sync_rows()`        règle les rangées neuves (grisés, saisies).

Tout cela s'appelle sous `prevent()` : les gestionnaires du formulaire ne
voient pas les valeurs reposées, sans quoi un profil ou une branche reposés
effaceraient les surcharges qu'on vient de remettre.
"""

import copy
import time

from script.todo.deploy_form_lib import FREE, t

# Au-delà, la plus ancienne entrée part : deux cents états couvrent une
# séance de saisie, et chaque instantané copie les surcharges.
HISTORY_CAP = 200
# Silence après lequel une suite de messages forme UN état : une frappe de
# « 8192 » émet quatre Changed, F7 en émet un par version cochée.
SETTLE_DELAY = 0.5
# Les frappes successives dans un même champ, à moins de ce délai de la
# précédente entrée, la complètent au lieu d'en ajouter une.
MERGE_DELAY = 3.0
# Libellé de valeur au-delà duquel on coupe : une ligne de la liste doit
# tenir sur une ligne.
VALUE_WIDTH = 30

# Le libellé lisible des champs que leur widget ne nomme pas lui-même. Une
# case porte son libellé ; une liste ou une saisie, seulement son id.
FIELD_NAMES = {
    "f_type": "VM type (default):",
    "f_store": "Application store:",
    "f_python": "Python interpreter:",
    "f_tz_sel": "Timezone",
    "f_tz": "Timezone",
    "f_ai_agent": "AI coding tools",
    "f_par": "Parallelism",
    "f_vcpus": "vCPU",
    "c_vcpus": "vCPU",
    "f_ram": "RAM",
    "c_ram": "RAM",
    "f_disk": "Disk",
    "c_disk": "Disk",
    "f_branch": "ERPLibre branch",
    "f_profile_install": "Install profile",
    "f_key": "SSH public key path",
    "f_git_name": "Name for git",
    "f_git_email": "Email for git",
}

# Les champs d'une surcharge, tels que la liste les nomme.
OVERRIDE_NAMES = {
    "vcpus": "vCPU",
    "ram": "RAM",
    "disk": "Disk",
    "desktop": "VM type (default):",
    "branch": "ERPLibre branch",
    "install_cmd": "Install profile",
}


class History:
    """Une liste d'états et un curseur sur l'état affiché.

    Chaque entrée : {"id", "label", "snap", "at", "key"}. L'id ne change
    jamais, même quand le plafond fait partir les plus anciennes : la liste
    désigne une entrée par lui, pas par son rang. `key` est l'id du champ
    quand l'entrée ne vient que de frappes dans ce champ, sinon None."""

    def __init__(self, snap, label, now, cap=HISTORY_CAP):
        self.entries = [
            {"id": 0, "label": label, "snap": snap, "at": now, "key": None}
        ]
        self.cursor = 0
        self.cap = cap
        self._next = 1

    @property
    def current(self):
        return self.entries[self.cursor]

    def _append(self, label, snap, now, key):
        entry = {
            "id": self._next,
            "label": label,
            "snap": snap,
            "at": now,
            "key": key,
        }
        self._next += 1
        self.entries.append(entry)
        while len(self.entries) > self.cap:
            self.entries.pop(0)
        self.cursor = len(self.entries) - 1
        return entry

    def record(self, label, snap, now, key=None, back=None):
        """Ajoute l'état `snap`, atteint depuis l'état courant.

        Curseur en arrière : l'état courant est d'abord rejoué en tête, sous
        le libellé `back(label de l'état courant)`, pour que rien de ce qu'on
        avait sauté ne se perde. Curseur en tête : une frappe dans le même
        champ que l'entrée de tête, assez proche, la complète — ou la retire,
        si elle ramène l'état d'avant."""
        if self.cursor < len(self.entries) - 1:
            quitte = self.current
            libelle = back(quitte["label"]) if back else quitte["label"]
            self._append(libelle, quitte["snap"], now, None)
        else:
            tete = self.entries[-1]
            if (
                key
                and self.cursor > 0
                and tete["key"] == key
                and now - tete["at"] < MERGE_DELAY
            ):
                if self.entries[-2]["snap"] == snap:
                    # La frappe revient à l'état d'avant : l'entrée n'a plus
                    # rien à défaire.
                    self.entries.pop()
                    self.cursor = len(self.entries) - 1
                    return self.current
                tete.update(label=label, snap=snap, at=now)
                return tete
        return self._append(label, snap, now, key)

    def undo(self):
        """(entrée défaite, entrée atteinte), ou None au début."""
        if self.cursor == 0:
            return None
        defaite = self.current
        self.cursor -= 1
        return defaite, self.current

    def redo(self):
        """L'entrée atteinte, ou None en tête."""
        if self.cursor >= len(self.entries) - 1:
            return None
        self.cursor += 1
        return self.current

    def jump(self, entry_id):
        """L'entrée d'id `entry_id`, devenue courante, ou None."""
        for index, entry in enumerate(self.entries):
            if entry["id"] == entry_id:
                self.cursor = index
                return entry
        return None


def _vm_name(key, overrides):
    """Le nom de la VM d'identité `key` : celui qu'on lui a donné, sinon
    sa distribution et sa version, et son numéro d'exemplaire."""
    name = (overrides.get(key) or {}).get("name")
    if name:
        return name
    distro, version, _arch, instance = key
    return f"{distro} {version}" + (f" #{instance + 1}" if instance else "")


def _fmt(value, choices=None):
    """Une valeur de champ, telle qu'on la lit dans la liste."""
    if isinstance(value, bool):
        return "✓" if value else "✗"
    if choices is not None:
        try:
            if value in choices:
                return _clip(choices[value])
        except TypeError:
            pass
    if value is FREE:
        return t("free value…")
    if value is None or type(value).__name__ == "NoSelection":
        return "—"
    return _clip(value)


def _clip(value):
    text = str(value)
    return text if len(text) <= VALUE_WIDTH else text[: VALUE_WIDTH - 1] + "…"


def describe(before, after, info=None):
    """Ce qui change entre deux instantanés, en morceaux lisibles.

    `info` : {"names": {id: libellé}, "choices": {id: {valeur: texte}}}, ce
    que les widgets disent d'eux-mêmes. Le catalogue d'abord, parce qu'un
    geste de masse est ce qu'on cherche des yeux dans la liste."""
    info = info or {}
    names = info.get("names") or {}
    choices = info.get("choices") or {}
    parts = []
    avant, apres = set(before.get("catalog", ())), set(
        after.get("catalog", ())
    )
    if apres - avant:
        parts.append(f"+{len(apres - avant)} VM")
    if avant - apres:
        parts.append(f"−{len(avant - apres)} VM")
    if before.get("arch") != after.get("arch"):
        parts.append(f"{t('Architecture')} : {after.get('arch')}")
    if before.get("profile") != after.get("profile"):
        profil = after.get("profile")
        parts.append(
            f"{t('Resources')} : "
            + (t("custom") if profil == "custom" else f"x{profil}")
        )
    copies_av, copies_ap = before.get("copies", {}), after.get("copies", {})
    for base in sorted(set(copies_av) | set(copies_ap)):
        delta = copies_ap.get(base, 0) - copies_av.get(base, 0)
        if delta:
            signe = "+" if delta > 0 else "−"
            parts.append(
                f"{signe}{abs(delta)} {t('copy')} {base[0]} {base[1]}"
            )
    over_av = before.get("overrides", {})
    over_ap = after.get("overrides", {})
    lock_av, lock_ap = before.get("locked", set()), after.get("locked", set())
    for key in sorted(set(lock_ap) - set(lock_av)):
        parts.append(f"🔒 {_vm_name(key, over_ap)}")
    for key in sorted(set(lock_av) - set(lock_ap)):
        parts.append(f"🔓 {_vm_name(key, over_av)}")
    for key in sorted(set(over_av) | set(over_ap)):
        if key in set(lock_av) ^ set(lock_ap):
            # Le verrou recopie ou retire tout d'un coup : le cadenas suffit.
            continue
        av, ap = over_av.get(key) or {}, over_ap.get(key) or {}
        if av == ap:
            continue
        nom = _vm_name(key, over_ap if ap else over_av)
        if av.get("name") != ap.get("name"):
            parts.append(
                f"{_vm_name(key, over_av)} → {_vm_name(key, over_ap)}"
            )
        if not ap:
            parts.append(f"{nom} : {t('common settings')}")
            continue
        for field in OVERRIDE_NAMES:
            if av.get(field) != ap.get(field):
                valeur = ap.get(field)
                if field == "install_cmd":
                    valeur = ap.get("install_label") or valeur
                parts.append(
                    f"{nom} : {t(OVERRIDE_NAMES[field]).rstrip(': ')} "
                    f"{_fmt(valeur) if valeur is not None else '—'}"
                )
    custom_av, custom_ap = before.get("custom", {}), after.get("custom", {})
    for field in sorted(set(custom_av) | set(custom_ap)):
        if custom_av.get(field) != custom_ap.get(field):
            nom = t(OVERRIDE_NAMES.get(field, field)).rstrip(": ")
            parts.append(f"{nom} : {_fmt(custom_ap.get(field))}")
    wid_av, wid_ap = before.get("widgets", {}), after.get("widgets", {})
    for wid in sorted(set(wid_av) | set(wid_ap)):
        if wid_av.get(wid) == wid_ap.get(wid):
            continue
        # La saisie libre d'une ressource double sa valeur commune, déjà
        # dite par « custom ».
        if wid in ("c_vcpus", "c_ram", "c_disk") and custom_av != custom_ap:
            continue
        nom = names.get(wid) or wid
        parts.append(f"{nom} : {_fmt(wid_ap.get(wid), choices.get(wid))}")
    return parts


def label_for(parts, action=None):
    """Le libellé d'une entrée : le premier changement, et combien d'autres
    l'accompagnent. Le geste qui l'a causé, quand on le connaît, vient en
    tête : « F6 Tout — +18 VM »."""
    texte = parts[0] if parts else "…"
    if len(parts) > 1:
        texte += f" (+{len(parts) - 1})"
    return f"{action} — {texte}" if action else texte


# --------------------------------------------------------------------------- #
# La liste, construite au premier appel : ce module se lit sans Textual.
# --------------------------------------------------------------------------- #
_ECRAN = {}


def _build_screen():
    from textual.app import ComposeResult
    from textual.containers import Vertical
    from textual.markup import escape
    from textual.screen import ModalScreen
    from textual.widgets import OptionList, Static
    from textual.widgets.option_list import Option

    class HistoryScreen(ModalScreen):
        """Les états du formulaire, le plus récent en haut.

        Entrée rend l'id de l'entrée choisie ; Échap, « h » ou F2 rendent
        None. La fenêtre ne change rien elle-même : le formulaire restaure
        après sa fermeture."""

        BINDINGS = [
            ("escape", "close", t("Close")),
            ("h", "close", t("Close")),
            ("f2", "close", t("Close")),
        ]

        def __init__(self, entries, cursor):
            super().__init__()
            self._entries = entries
            self._cursor = cursor

        def compose(self) -> ComposeResult:
            options = []
            for index in range(len(self._entries) - 1, -1, -1):
                entry = self._entries[index]
                heure = time.strftime("%H:%M:%S", time.localtime(entry["at"]))
                # Un libellé reprend ce qu'on a tapé — un nom de VM, un nom
                # git — et un « [ » y serait lu comme une balise : échappé,
                # sinon « a[/] » ferait tomber le formulaire entier.
                libelle = escape(entry["label"])
                if index == self._cursor:
                    texte = f"● {heure}  {libelle}"
                elif index > self._cursor:
                    texte = (
                        f"[dim]  {heure}  {libelle}  "
                        f"({t('undone — ctrl+y')})[/dim]"
                    )
                else:
                    texte = f"  {heure}  {libelle}"
                options.append(Option(texte, id=str(entry["id"])))
            with Vertical(id="histbox"):
                yield Static(
                    f"  {t('Modification history')}   "
                    f"({t('Enter: back to this state · Esc: close · ctrl+z / ctrl+y in the form: one step')})",
                    id="histtitle",
                )
                yield OptionList(*options, id="histlist")

        def on_mount(self) -> None:
            liste = self.query_one("#histlist", OptionList)
            liste.highlighted = len(self._entries) - 1 - self._cursor
            liste.focus()

        def on_option_list_option_selected(self, event) -> None:
            self.dismiss(int(event.option.id))

        def action_close(self) -> None:
            self.dismiss(None)

    return HistoryScreen


def history_screen():
    """La fenêtre de l'historique, construite au premier appel."""
    if not _ECRAN:
        _ECRAN["history"] = _build_screen()
    return _ECRAN["history"]


# --------------------------------------------------------------------------- #
# Le branchement dans un formulaire
# --------------------------------------------------------------------------- #
_SANS_CLE = object()


class HistoryMixin:
    """L'historique d'un formulaire de déploiement. À placer AVANT les
    autres mixins dans la liste des bases : ses gestionnaires de messages
    s'ajoutent à ceux du formulaire, que Textual appelle d'abord."""

    # Champs que le modèle porte déjà, et que `_hist_restore_radios`
    # presse lui-même.
    HIST_MODEL_WIDGETS = ("f_arch", "f_profile")
    _HIST_QUERY = (
        "#fields Input, #fields Checkbox, #fields Select, #fields RadioSet"
    )

    def hist_init(self) -> None:
        """À appeler dans `__init__`. L'origine n'est prise qu'au premier
        silence après le montage : les échos du montage la précèdent."""
        self._hist = None
        self._hist_last = None
        self._hist_timer = None
        self._hist_label = None
        self._hist_key = _SANS_CLE
        self._hist_restoring = False
        # Un message est arrivé pendant une restauration : il sera relevé
        # après elle, et non perdu dans sa base de comparaison.
        self._hist_pending = False
        # Les gestes reçus pendant une restauration, joués après elle.
        self._hist_waiting = []

    # ---------------------------------------------------------------- #
    # Prendre et comparer
    # ---------------------------------------------------------------- #
    def _hist_snapshot(self):
        from textual.widgets import RadioSet

        widgets = {}
        for widget in self.query(self._HIST_QUERY):
            if not widget.id or widget.id in self.HIST_MODEL_WIDGETS:
                continue
            widgets[widget.id] = (
                widget.pressed_index
                if isinstance(widget, RadioSet)
                else widget.value
            )
        snap = {
            attr: copy.deepcopy(getattr(self, attr, None))
            for attr in self._hist_model_attrs()
        }
        snap["catalog"] = self._hist_catalog()
        snap["widgets"] = widgets
        return snap

    def _hist_info(self):
        """Les noms et les choix que les widgets donnent d'eux-mêmes."""
        from textual.widgets import Checkbox, RadioButton, RadioSet, Select

        names, choices = {}, {}
        for widget in self.query(self._HIST_QUERY):
            if not widget.id:
                continue
            if isinstance(widget, Checkbox):
                label = getattr(widget.label, "plain", str(widget.label))
                # Une case d'outil se lit « Nom +N Go — indice » : le nom
                # suffit à la reconnaître.
                names[widget.id] = label.split(" +")[0].split(" — ")[0]
                continue
            cle = FIELD_NAMES.get(widget.id)
            if cle:
                names[widget.id] = t(cle).rstrip(": ")
            if isinstance(widget, RadioSet):
                choices[widget.id] = {
                    i: getattr(b.label, "plain", str(b.label))
                    for i, b in enumerate(widget.query(RadioButton))
                }
            elif isinstance(widget, Select):
                table = {}
                for prompt, value in getattr(widget, "_options", ()):
                    try:
                        table[value] = getattr(prompt, "plain", str(prompt))
                    except TypeError:
                        continue
                choices[widget.id] = table
        return {"names": names, "choices": choices}

    def _hist_touch(self, key=None) -> None:
        """Quelque chose a peut-être changé : l'état sera relevé au premier
        silence.

        `key` est l'id du champ de saisie tapé, None pour tout autre message.
        Une fenêtre dont toutes les frappes viennent du même champ garde ce
        champ, et peut compléter l'entrée précédente. Les autres messages ne
        comptent pas : chaque frappe dans une ressource remonte les rangées,
        dont les échos briseraient sinon la fusion."""
        restoring = getattr(self, "_hist_restoring", None)
        if restoring is None:
            return
        if restoring:
            self._hist_pending = True
            return
        if key is not None:
            self._hist_key = key if self._hist_key in (_SANS_CLE, key) else ""
        if self._hist_timer is not None:
            self._hist_timer.stop()
        self._hist_timer = self.set_timer(SETTLE_DELAY, self._hist_settle)

    def _hist_gesture(self, label, fn) -> None:
        """Un geste nommé (F4, F6, F7, F8) : sa propre entrée, sous son nom.

        Ce qui attendait le silence est relevé AVANT — sinon un ctrl+z après
        F6 emporterait aussi le réglage fait juste avant —, et l'effet du
        geste APRÈS, tout de suite : un geste qui ne change rien ne laisse
        alors ni entrée ni nom à la modification suivante."""
        if self._hist_wait(lambda: self._hist_gesture(label, fn)):
            return
        self._hist_settle()
        fn()
        self._hist_label = label
        self._hist_settle()

    def _hist_wait(self, fn) -> bool:
        """Pendant une restauration, met `fn` de côté et rend True : un
        geste joué sur un état à moitié remis — F5 déploierait le plan
        d'avant l'annulation — attend qu'elle soit finie."""
        if not getattr(self, "_hist_restoring", False):
            return False
        self._hist_waiting.append(fn)
        return True

    def _hist_settle(self) -> None:
        """Relève l'état et l'ajoute s'il a changé. Appelée par le minuteur,
        et AVANT toute annulation : un ctrl+z pressé aussitôt après F6 doit
        défaire F6, pas l'état d'avant."""
        if self._hist_timer is not None:
            self._hist_timer.stop()
            self._hist_timer = None
        label, key = self._hist_label, self._hist_key
        self._hist_label, self._hist_key = None, _SANS_CLE
        if self._hist_restoring or not self.is_running:
            return
        try:
            snap = self._hist_snapshot()
        except Exception:
            # Le formulaire se démonte : il n'y a plus rien à relever.
            return
        now = time.time()
        if self._hist is None:
            self._hist = History(snap, t("Form opened"), now)
            self._hist_last = snap
            return
        if snap == self._hist_last:
            return
        parts = describe(self._hist_last, snap, self._hist_info())
        self._hist.record(
            label_for(parts, label),
            snap,
            now,
            key=key if key not in (_SANS_CLE, "") else None,
            back=lambda quitte: f"↶ {t('back to')} : {quitte}",
        )
        self._hist_last = snap

    # Les gestionnaires PAR NOM : Textual appelle ceux de chaque classe de la
    # chaîne d'héritage, après ceux du formulaire. Un « @on » posé dans une
    # mixin simple, sans la métaclasse de Textual, ne serait jamais appelé.
    def on_input_changed(self, event) -> None:
        self._hist_touch(key=event.input.id or "")

    def on_checkbox_changed(self, event) -> None:
        self._hist_touch()

    def on_select_changed(self, event) -> None:
        self._hist_touch()

    def on_radio_set_changed(self, event) -> None:
        self._hist_touch()

    def on_selection_list_selected_changed(self, event) -> None:
        self._hist_touch()

    def on_button_pressed(self, event) -> None:
        self._hist_touch()

    # ---------------------------------------------------------------- #
    # Revenir
    # ---------------------------------------------------------------- #
    def action_undo(self) -> None:
        if self._hist_wait(self.action_undo):
            return
        self._hist_settle()
        pas = self._hist.undo() if self._hist else None
        if pas is None:
            self.notify(t("Nothing to undo."))
            return
        defaite, atteinte = pas
        self._hist_restore(atteinte["snap"])
        # Sans balisage : le libellé reprend ce qu'on a tapé.
        self.notify(f"↶ {t('Undone:')} {defaite['label']}", markup=False)

    def action_redo(self) -> None:
        if self._hist_wait(self.action_redo):
            return
        self._hist_settle()
        atteinte = self._hist.redo() if self._hist else None
        if atteinte is None:
            self.notify(t("Nothing to redo."))
            return
        self._hist_restore(atteinte["snap"])
        self.notify(f"↷ {t('Redone:')} {atteinte['label']}", markup=False)

    def action_history(self) -> None:
        if self._hist_wait(self.action_history):
            return
        self._hist_settle()
        if self._hist is None:
            return

        def choisi(entry_id):
            if entry_id is None or self._hist is None:
                return
            if self._hist_wait(lambda: choisi(entry_id)):
                return
            courant = self._hist.current["id"]
            atteinte = self._hist.jump(entry_id)
            if atteinte is None or atteinte["id"] == courant:
                return
            self._hist_restore(atteinte["snap"])
            self.notify(f"{t('Back to:')} {atteinte['label']}", markup=False)

        self.push_screen(
            history_screen()(list(self._hist.entries), self._hist.cursor),
            choisi,
        )

    def _hist_put(self, wid, value) -> None:
        """Repose la valeur d'un champ. Une valeur que le champ n'offre plus
        est laissée de côté plutôt que de lever."""
        from textual.widgets import RadioButton, RadioSet, Select

        try:
            widget = self.query_one(f"#{wid}")
        except Exception:
            return
        try:
            if isinstance(widget, RadioSet):
                boutons = list(widget.query(RadioButton))
                if 0 <= value < len(boutons):
                    boutons[value].value = True
            elif isinstance(widget, Select) and (
                type(value).__name__ == "NoSelection"
            ):
                widget.clear()
            elif widget.value != value:
                widget.value = value
        except Exception:
            pass

    def _hist_restore(self, snap) -> None:
        """Remet le formulaire dans l'état `snap`.

        Le modèle d'abord, puis les champs sous `prevent()`, puis — après un
        rafraîchissement, le temps que les RadioSet prennent leur bouton —
        ce qui en découle et le plan."""
        from textual.widgets import (
            Checkbox,
            Input,
            RadioSet,
            Select,
            SelectionList,
        )

        if self._hist_timer is not None:
            self._hist_timer.stop()
            self._hist_timer = None
        self._hist_label, self._hist_key = None, _SANS_CLE
        self._hist_restoring = True
        self._hist_pending = False
        for attr in self._hist_model_attrs():
            setattr(self, attr, copy.deepcopy(snap.get(attr)))
        with self.prevent(
            Input.Changed,
            Checkbox.Changed,
            Select.Changed,
            RadioSet.Changed,
            SelectionList.SelectedChanged,
        ):
            self._hist_restore_catalog(snap)
            self._hist_restore_radios(snap)
            for wid, value in snap["widgets"].items():
                self._hist_put(wid, value)
        # Les confirmations « F5 à nouveau » valaient pour le plan d'avant.
        self._offline_ack = False
        self._orphan_ack = False
        self.call_after_refresh(self._hist_restore_end, snap)

    def _hist_restore_end(self, snap) -> None:
        from textual.widgets import Checkbox, Input, RadioSet, Select

        with self.prevent(
            Input.Changed, Checkbox.Changed, Select.Changed, RadioSet.Changed
        ):
            self._hist_sync_derived(snap)
        self._hist_rebuild()
        # Après le montage des rangées, que le plan vient de demander.
        self.call_after_refresh(self._hist_restore_done, snap)

    def _hist_restore_done(self, snap) -> None:
        """La fin d'une restauration : les rangées neuves réglées, puis ce
        qui est arrivé pendant qu'elle se faisait."""
        # Le réglage des rangées qui suit leur montage a pu viser les
        # anciennes, encore là le temps de leur retrait : il est refait sur
        # les neuves.
        self._hist_sync_rows()
        self._hist_last = snap
        self._hist_restoring = False
        if self._hist_pending:
            # Un changement fait pendant la restauration devient sa propre
            # entrée ; les échos du montage, identiques à la cible, aucune.
            self._hist_pending = False
            self._hist_touch(key="")
        if self.focused is None:
            self._catalog().focus()
        attente, self._hist_waiting = self._hist_waiting, []
        for fn in attente:
            fn()
