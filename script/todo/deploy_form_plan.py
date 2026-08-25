#!/usr/bin/env python3
# © 2021-2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Le PLAN d'un déploiement : son état, ses gestes, ses deux fenêtres.

Un plan de déploiement se manipule pareil qu'on visse sur libvirt ou sur
Proxmox : on choisit des entrées du catalogue, on en demande plusieurs
exemplaires, on renomme une machine, on règle une ressource sur une seule
ligne, on fige celle qui doit échapper au réglage commun. Cette mécanique
— surcharges, verrous, exemplaires, saisies libres — n'a rien d'un
hyperviseur ; elle est ici, une seule fois, et les deux formulaires en
héritent.

Ce que le formulaire hôte doit fournir (le contrat, court exprès) :

* attributs  `rows`, `vms`, `copies`, `overrides`, `locked`, `custom`,
  `profile`, `_gen`, `_shown_ids` ;
* méthodes   `_selected_entries()`, `_recompute()`, `_mount_rows()`,
  `_render_plan()` ;
* crochets   `_presets()` (choix par ressource), `_auto_name(index)` (le nom
  que la VM reprendrait si on effaçait le sien) et `_lock_fields(index)` (ce
  qu'un verrou recopie, ressources comprises).

Rien d'autre : le mixin ne connaît ni bureau, ni branche, ni stockage.
"""

import re

from script.todo.deploy_form_lib import (
    FREE,
    RES_FIELDS,
    clean_hostname,
    entry_key,
    expand_copies,
    parse_disk,
    parse_ram,
    positive_int,
    t,
)

# Champs qui ne veulent rien dire l'un sans l'autre : retirer la commande
# d'installation doit emporter son libellé, sinon le plan afficherait
# « Odoo 18 » à côté d'une VM qui n'installe plus rien.
COMPANIONS = {"install_cmd": ("install_label",)}

# Les écrans sont construits à l'APPEL, pas à l'import : ce module se lit sans
# Textual installé (le CLI TODO l'importe pour ses fonctions pures).
_ECRANS = {}


def _build_screens():
    from textual.app import ComposeResult
    from textual.containers import Horizontal, Vertical
    from textual.screen import ModalScreen
    from textual.widgets import Button, Input, Static

    class RenameScreen(ModalScreen):
        """Nom d'une VM. Vide = revenir au nom automatique."""

        BINDINGS = [("escape", "cancel", t("Cancel"))]

        def __init__(self, name, auto):
            super().__init__()
            self._name = name
            self._auto = auto

        def compose(self) -> ComposeResult:
            with Vertical(id="renbox"):
                yield Static(t("Rename the VM"), id="rentitle")
                yield Input(value=self._name, id="renval")
                yield Static(
                    f"  {t('Empty = back to the automatic name:')} "
                    f"{self._auto}",
                    id="renhint",
                )
                with Horizontal(id="renbtns"):
                    yield Button(t("Cancel"), id="ren_no")
                    yield Button(t("Rename"), variant="primary", id="ren_ok")

        def on_button_pressed(self, event) -> None:
            if event.button.id != "ren_ok":
                self.dismiss(None)
                return
            self.dismiss(self.query_one("#renval", Input).value)

        def action_cancel(self) -> None:
            self.dismiss(None)

    class PreviewScreen(ModalScreen):
        """Aperçu des commandes qui seraient lancées (aucune exécution)."""

        BINDINGS = [
            ("escape", "close", t("Close")),
            ("q", "close", t("Close")),
        ]

        def __init__(self, lines):
            super().__init__()
            self._lines = lines

        def compose(self) -> ComposeResult:
            with Vertical(id="prevbox"):
                yield Static(
                    f"  {t('Preview (dry-run):')}   ({t('Esc to close')})",
                    id="prevtitle",
                )
                yield Static("\n\n".join(self._lines), id="prevbody")

        def action_close(self) -> None:
            self.dismiss()

    return {"rename": RenameScreen, "preview": PreviewScreen}


def rename_screen():
    """La fenêtre de renommage, construite au premier appel."""
    if not _ECRANS:
        _ECRANS.update(_build_screens())
    return _ECRANS["rename"]


def preview_screen():
    """La fenêtre d'aperçu, construite au premier appel."""
    if not _ECRANS:
        _ECRANS.update(_build_screens())
    return _ECRANS["preview"]


class PlanMixin:
    """Les gestes du plan, communs à tous les formulaires de déploiement."""

    # ---------------------------------------------------------------- #
    # Le jeu de VM affiché
    # ---------------------------------------------------------------- #
    def _plan_entries(self):
        """Entrées du plan : la sélection, dépliée en exemplaires."""
        return expand_copies(self._selected_entries(), self.copies)

    def _row_ids(self):
        """Identité du JEU de VM affiché. Reconstruire les widgets à chaque
        frappe ferait perdre le focus en pleine saisie : on ne le fait que
        si la liste elle-même a changé."""
        return tuple(entry_key(e) for e in self._plan_entries())

    def _row_key(self, index):
        entries = self._plan_entries()
        return entry_key(entries[index]) if index < len(entries) else None

    def _is_current(self, widget):
        """Le widget appartient-il au jeu de rangées ACTUEL ?"""
        return getattr(widget, "_el_gen", None) == self._gen

    def _focused_row(self):
        """Rang de la VM dont un widget a le focus, ou None. C'est la seule
        désignation qui ait un sens ici : il n'y a plus de curseur unique,
        chaque rangée est éditable directement."""
        wid = getattr(self.focused, "id", "") or ""
        match = re.match(r"[vch](\d+)(?:_|$)", wid)
        if not match:
            return None
        index = int(match.group(1))
        return index if 0 <= index < len(self.rows) else None

    def _row_head(self, index, row):
        """Ligne de titre d'une VM : nom, origine, état, marque de
        personnalisation. Sans elle, deux rangées aux réglages différents
        n'ont aucune explication à l'écran."""
        vm = row["vm"]
        icon = {"new": "", "exists": "⏭ ", "orphan": "❌ "}[row["state"]]
        state = "" if row["state"] == "new" else f"  {icon}{row['note']}"
        if row.get("locked"):
            mark = "  🔒 figée"
        elif row.get("custom"):
            mark = "  ✎"
        else:
            mark = ""
        return (
            f"[b]{vm['name']}[/b]  {vm['distro']} {vm['version']} "
            f"[{vm['arch']}]  {row['disk_gb']}G{state}{mark}"
        )

    def _row_echo(self, index, field, value) -> bool:
        """Cette valeur est-elle l'ÉCHO du montage plutôt qu'une saisie ?

        Poser « value= » sur un Select fait émettre un Changed que Textual
        délivre APRÈS coup : un verrou temporel ne l'attrape pas — mesuré, les
        trois champs de chaque VM se retrouvaient surchargés dès l'affichage
        et le réglage commun devenait inopérant. On compare donc à ce que le
        modèle dit déjà : une valeur identique n'est pas une saisie.

        Cas limite assumé : choisir explicitement la valeur que le réglage
        commun donne déjà n'enregistre pas de surcharge. La VM suivra donc ce
        réglage s'il change — ce qui est aussi le plus attendu quand on n'a
        rien changé de visible."""
        if index >= len(self.rows):
            return True
        return value == self.rows[index]["vm"].get(field)

    # ---------------------------------------------------------------- #
    # Surcharges : ce qu'une VM garde quand le réglage commun change
    # ---------------------------------------------------------------- #
    def _set_override(self, index, field, value) -> None:
        """Écrit — ou retire — la surcharge d'UNE VM."""
        key = self._row_key(index)
        if key is None:
            return
        if value in ("", 0, None):
            # Saisie vidée ou invalide : on RETIRE la surcharge au lieu
            # d'écrire un zéro, qui donnerait une VM à 0 vCPU.
            self.overrides.get(key, {}).pop(field, None)
            if not self.overrides.get(key):
                self.overrides.pop(key, None)
        else:
            self.overrides.setdefault(key, {})[field] = value

    def _clear_overrides(self, fields) -> None:
        """Rend au choix commun les VM NON figées, pour ces champs-là.

        Le cadenas est la seule chose qui résiste. Une valeur réglée à la
        main sur une rangée cède donc au choix global suivant : c'est ce
        qu'on attend d'un réglage « général », et le verrou existe
        précisément pour dire « pas celle-ci ».

        Par champ, pas en bloc : changer la RAM générale n'a aucune raison
        d'effacer le disque qu'on a réglé sur une VM.

        « name » n'y figure jamais : un renommage est explicite et ne
        découle d'aucune valeur générale."""
        changed = False
        for key in list(self.overrides):
            if key in self.locked:
                continue
            for field in fields:
                changed |= self.overrides[key].pop(field, None) is not None
                for compagnon in COMPANIONS.get(field, ()):
                    self.overrides[key].pop(compagnon, None)
            if not self.overrides[key]:
                self.overrides.pop(key, None)
        if changed:
            # Forcer le remontage : une rangée peut porter une saisie
            # LIBRE, que le simple rafraîchissement laisse en place — on
            # verrait « 12 » à l'écran pendant que la VM vaut 2. Le
            # remontage rebâtit tout depuis le modèle. Sans risque de vol
            # de focus : ce chemin part d'un widget GLOBAL, jamais d'une
            # rangée.
            self._shown_ids = ()

    def _set_lock(self, index, on) -> None:
        """Fige — ou libère — les ressources d'une VM.

        Figer, c'est recopier les valeurs EFFECTIVES du moment dans les
        surcharges : le profil commun ne les atteint plus. Libérer les
        retire, et la VM retombe sous le profil. Le mécanisme est celui
        des surcharges, déjà éprouvé ; le verrou n'en est que la commande
        explicite, et il couvre tous les champs d'un coup.

        `_lock_fields` dit CE QUI est recopié : chaque formulaire y ajoute
        ce qui, chez lui, vient d'un choix commun."""
        from textual.containers import VerticalScroll
        from textual.widgets import Button

        key = self._row_key(index)
        if key is None or index >= len(self.rows):
            return
        if on:
            self.locked.add(key)
            self.overrides[key] = self._lock_fields(index)
        else:
            self.locked.discard(key)
            self.overrides.pop(key, None)
        self._recompute()
        # La couleur de la ligne suit le verrou sans tout remonter : un
        # remontage volerait le focus à la case qu'on vient de cocher.
        cards = self.query_one("#plan", VerticalScroll).children
        if index < len(cards):
            cards[index].set_class(on, "locked")
        btn = self.query_one(f"#l{index}", Button)
        btn.label = "🔒" if on else "🔓"
        btn.variant = "success" if on else "default"

    def _lock_fields(self, index):
        """Ce qu'un verrou recopie. Les ressources, au minimum."""
        vm = self.rows[index]["vm"]
        return {"vcpus": vm["vcpus"], "ram": vm["ram"], "disk": vm["disk"]}

    # ---------------------------------------------------------------- #
    # Exemplaires et renommage
    # ---------------------------------------------------------------- #
    def _add_copy(self, index, delta) -> None:
        """Ajoute ou retire un exemplaire de l'entrée visée.

        Retirer enlève le DERNIER exemplaire, et avec lui ses réglages :
        les garder ferait resurgir d'anciennes valeurs à la copie
        suivante, sans que rien ne l'explique."""
        entries = self._plan_entries()
        if index >= len(entries):
            return
        item = entries[index]
        base = (item["distro"], item["version"], item["arch"])
        count = self.copies.get(base, 0)
        if delta > 0:
            self.copies[base] = count + 1
        else:
            if count <= 0:
                return
            gone = (*base, count)
            self.overrides.pop(gone, None)
            self.locked.discard(gone)
            self.copies[base] = count - 1
            if not self.copies[base]:
                self.copies.pop(base, None)
        self._recompute()
        # Le JEU de VM a changé : les rangées doivent être rebâties.
        self._mount_rows()

    def _rename(self, index) -> None:
        """Renomme une VM. Le nom saisi devient une surcharge comme les
        autres : il survit au recalcul, et F4 le retire avec le reste."""
        key = self._row_key(index)
        if key is None or index >= len(self.rows):
            return
        auto = self._auto_name(index)

        def done(value):
            if value is None:
                return
            if not str(value).strip():
                self.overrides.get(key, {}).pop("name", None)
                if not self.overrides.get(key):
                    self.overrides.pop(key, None)
            else:
                clean = clean_hostname(value)
                if not clean:
                    self.notify(
                        t("Invalid name: letters, digits, hyphens."),
                        severity="error",
                    )
                    return
                self.overrides.setdefault(key, {})["name"] = clean
            self._recompute()
            self._mount_rows()

        self.push_screen(
            rename_screen()(self.rows[index]["vm"]["name"], auto), done
        )

    # ---------------------------------------------------------------- #
    # Le catalogue — les trois raccourcis de sélection
    # ---------------------------------------------------------------- #
    def _catalog(self):
        from textual.widgets import SelectionList

        return self.query_one("#f_catalog", SelectionList)

    def action_select_all(self) -> None:
        self._catalog().select_all()

    def action_select_none(self) -> None:
        self._catalog().deselect_all()

    def action_select_main(self) -> None:
        """Une VM par distribution : la version marquée par défaut.

        Ici et non dans un formulaire : les trois gestes sont les mêmes des
        deux côtés, et celui-ci manquait à l'écran Proxmox — qui affiche
        pourtant le même catalogue, drapeau « default » compris."""
        widget = self._catalog()
        widget.deselect_all()
        for i, e in enumerate(self._entries()):
            if e.get("default"):
                widget.select(i)

    def _auto_name(self, index):
        """Nom que la VM reprendrait si on effaçait le sien."""
        return self._plan_entries()[index]["name"]

    # ---------------------------------------------------------------- #
    # Saisies libres — la valeur qui n'est pas dans la liste
    # ---------------------------------------------------------------- #
    def _row_free(self, index, field, visible) -> None:
        from textual.widgets import Input

        widget = self.query_one(f"#c{index}_{field}", Input)
        widget.display = bool(visible)
        widget.disabled = not visible
        if visible:
            widget.focus()

    def _read_row_free(self, index, field):
        from textual.widgets import Input

        raw = self.query_one(f"#c{index}_{field}", Input).value.strip()
        return self._read_res(field, raw)

    @staticmethod
    def _read_res(field, raw):
        """Lecture d'une ressource saisie à la main. Le disque se lit en
        tailles (« 40G »), la mémoire accepte les deux, le reste est un
        entier — et une valeur invalide vaut « rien », jamais zéro."""
        if field == "disk":
            return parse_disk(raw) or ""
        if field == "ram":
            return parse_ram(raw)
        return positive_int(raw, 0)

    def _show_free(self, field, visible) -> None:
        """Montre ou cache la saisie libre d'une ressource."""
        from textual.widgets import Input

        widget = self.query_one(RES_FIELDS[field][1], Input)
        widget.display = bool(visible)
        widget.disabled = not visible

    def _apply_free(self, field) -> None:
        """Relit la saisie libre. Une valeur invalide n'écrase rien : le
        profil retombe alors sur celle du catalogue."""
        from textual.widgets import Input

        raw = self.query_one(RES_FIELDS[field][1], Input).value.strip()
        self.custom[field] = self._read_res(field, raw)
        self._clear_overrides((field,))

    def _sync_free_inputs(self) -> None:
        """Chaque saisie libre de rangée s'affiche si — et seulement si — sa
        ressource échappe aux préréglages, ou si la liste attend une frappe."""
        from textual.widgets import Input, Select

        presets = self._presets()
        for i, r in enumerate(self.rows):
            vm = r["vm"]
            for field, choix in presets.items():
                try:
                    widget = self.query_one(f"#c{i}_{field}", Input)
                except Exception:
                    continue
                # Visible si la valeur EST libre, ou si la liste est
                # posée sur « libre… » en attente d'une saisie.
                try:
                    chosen_free = (
                        self.query_one(f"#v{i}_{field}", Select).value is FREE
                    )
                except Exception:
                    chosen_free = False
                free = chosen_free or vm[field] not in choix
                widget.display = free
                widget.disabled = not free
