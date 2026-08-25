#!/usr/bin/env python3
# © 2021-2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Ce qu'on installe DANS la VM, et qui ne regarde pas l'hyperviseur.

Type de VM, production, magasin d'applications, outils de développement,
fuseau horaire, interpréteur Python : six réglages qui décrivent le système
invité, pas la machine qui le porte. Ils valent donc mot pour mot sur libvirt
et sur Proxmox VE — et c'est exactement ce qui avait dérivé. L'écran QEMU/KVM
les portait tous, l'écran Proxmox trois : une VM créée là-bas naissait sans
bureau, sans outils et en UTC, sans que rien ne le dise.

La duplication était le mécanisme de la dérive, pas son symptôme : chaque
correctif se posait sur un seul des deux écrans. Ce module met les six ici,
une seule fois, widgets ET logique. Un formulaire hérite d'`ExtrasMixin`,
appelle `extras_init(ctx)` puis pose les fragments de `compose_*` où sa mise
en page les veut.

Le contrat côté formulaire, court exprès : l'attribut `vms` (les VM retenues)
et une case `#f_install`. Rien d'autre — ce module ne connaît ni stockage, ni
pont, ni domaine libvirt.

Chaque accès aux widgets est gardé : un formulaire n'est pas tenu de poser
tous les fragments, et lire un widget absent ne doit pas casser l'écran.
"""

from script.todo.deploy_form_lib import FREE, t

# Ce que l'écran lit du contexte. Une seule liste, parce que les deux
# formulaires doivent en recevoir autant : c'est en fournissant un
# sous-ensemble que l'écran Proxmox avait perdu la moitié des réglages.
_TABLES = (
    ("desktops", list, "desktops"),
    ("desktop_disk", int, "desktop_disk_gb"),
    ("app_stores", list, "app_stores"),
    ("snap_distros", set, "snap_distros"),
    ("timezones", list, "timezones"),
    ("timezone", str, "timezone"),
    ("vm_tools", list, "vm_tools"),
    ("tool_disk", dict, "vm_tool_disk"),
    ("tool_phases", dict, "vm_tool_phases"),
    ("tool_arches", dict, "vm_tool_arches"),
    ("tool_desktops", dict, "vm_tool_desktops"),
    ("tool_needs_desktop", dict, "vm_tool_needs_desktop"),
    ("tool_families", dict, "vm_tool_families"),
    ("distro_family", dict, "distro_family"),
    ("mise_arches", set, "mise_arches"),
    ("defaults", dict, "defaults"),
)


def extras_tables(ctx) -> dict:
    """Les tables lues du contexte, chacune ramenée à son type.

    Ramenées, et non prises telles quelles : une clé absente rend un vide du
    bon type, donc les prédicats plus bas n'ont aucun cas particulier à
    porter. Un formulaire qui n'offre pas les outils passe simplement un
    contexte sans « vm_tools »."""
    ctx = ctx or {}
    return {nom: kind(ctx.get(cle) or kind()) for nom, kind, cle in _TABLES}


def tools_for_vm(vm, tools, tab) -> list:
    """Outils qu'une VM donnée recevra VRAIMENT.

    Le même filtre que côté déploiement, et c'est le point : une VM ARM ne
    verra jamais Android Studio, une VM Cinnamon jamais les extensions GNOME,
    un serveur aucun des IDE — mais un serveur reçoit bien la compilation
    mobile, qui n'a rien à afficher, et une distribution sans apt ne la
    reçoit pas, son installateur n'existant que là.

    Filtrer ici plutôt que dans la commande distante permet d'annoncer
    l'écart AVANT le déploiement, au lieu de le laisser découvrir dans un
    journal d'installation d'une heure."""
    out = []
    for key in tools or ():
        arches = tab["tool_arches"].get(key) or ()
        desks = tab["tool_desktops"].get(key) or ()
        fams = tab["tool_families"].get(key) or ()
        if tab["tool_needs_desktop"].get(key) and not vm.get("desktop"):
            continue
        if arches and vm.get("arch") not in arches:
            continue
        if desks and vm.get("desktop") not in desks:
            continue
        if fams and tab["distro_family"].get(vm.get("distro"), "") not in fams:
            continue
        out.append(key)
    return out


def app_store_needed(vms, tab) -> bool:
    """Le choix du magasin n'a de sens que pour une VM GRAPHIQUE sur une
    distribution qui livre snapd. Ailleurs, rien ne tire de snap."""
    return any(
        vm.get("desktop") and vm.get("distro") in tab["snap_distros"]
        for vm in vms or ()
    )


def mise_usable(vms, tab) -> bool:
    """Au moins une VM retenue tourne sur une architecture que mise sert."""
    return any(vm.get("arch") in tab["mise_arches"] for vm in vms or ())


def extras_disk_gb(vm, tools, tab) -> int:
    """Go que le bureau et les outils ajoutent au disque de CETTE VM.

    De cette VM et d'elle seule : un supplément commun mentait dès que les
    types différaient d'une machine à l'autre, et gonflait le disque d'un
    serveur pour un bureau qu'il n'aurait pas."""
    gb = tab["desktop_disk"] if vm.get("desktop") else 0
    return gb + sum(
        tab["tool_disk"].get(k, 0) for k in tools_for_vm(vm, tools, tab)
    )


class ExtrasMixin:
    """Les six réglages du système invité, widgets et logique.

    Le formulaire hôte pose les fragments `compose_*` où il veut, appelle
    `render_extras()` après chaque recalcul et `extras_values()` au moment de
    bâtir sa spec."""

    def extras_init(self, ctx) -> None:
        """À appeler dans `__init__`, avant tout `compose`."""
        self._extras = extras_tables(ctx)

    # ------------------------------------------------------------------ #
    # Les widgets
    # ------------------------------------------------------------------ #
    def compose_vm_type(self):
        """Type de VM par défaut. Serveur d'abord : c'est ce que sert une
        image cloud, et un bureau ajoute une à deux heures sur une
        architecture émulée. Le plan annonce le surcoût disque."""
        from textual.widgets import RadioButton, RadioSet, Static

        tab = self._extras
        if not tab["desktops"]:
            return
        yield Static(t("VM type (default):"), classes="grouptitle")
        with RadioSet(id="f_type"):
            yield RadioButton(
                t("Server (no graphical interface)"),
                value=not tab["defaults"].get("desktop", ""),
            )
            for key, label in tab["desktops"]:
                yield RadioButton(
                    f"{t('Graphical (server + desktop):')} {label}",
                    value=tab["defaults"].get("desktop", "") == key,
                )

    def compose_install_extras(self):
        """Ce qui pend à la case « installer » : production, magasin,
        outils. Posé DANS la section « Installation », après la branche et le
        profil."""
        from textual.widgets import Checkbox, RadioButton, RadioSet, Static

        tab = self._extras
        yield Checkbox(
            t("Production (/opt, confined)"),
            value=tab["defaults"].get("prod", False),
            id="f_prod",
        )
        if tab["app_stores"]:
            yield Static(
                t("Application store:"), id="t_store", classes="grouptitle"
            )
            with RadioSet(id="f_store"):
                for i, (_k, label) in enumerate(tab["app_stores"]):
                    yield RadioButton(label, value=i == 0)
            yield Static("", id="storewarn")
        if tab["vm_tools"]:
            # Une case par outil, et non une liste déroulante : ils sont
            # indépendants, et chacun se prend ou se laisse.
            yield Static(
                t("Development tools:"), id="t_tools", classes="grouptitle"
            )
            for key, label, hint in tab["vm_tools"]:
                gb = tab["tool_disk"].get(key, 0)
                yield Checkbox(
                    f"{label} +{gb} Go — {hint}",
                    value=key in (tab["defaults"].get("tools") or ()),
                    id=f"f_tool_{key}",
                )
            yield Static("", id="toolwarn")

    def compose_timezone(self):
        """Une liste plutôt qu'une saisie : un nom IANA mal orthographié
        n'est pas refusé par cloud-init, il est IGNORÉ — la VM reste en UTC et
        on ne s'en aperçoit qu'aux horodatages. « libre… » garde la porte
        ouverte aux six cents autres fuseaux de la base."""
        from textual.widgets import Input, Select, Static

        tab = self._extras
        if not tab["timezones"]:
            return
        null = getattr(Select, "NULL", Select.BLANK)
        yield Static(t("Timezone"), classes="grouptitle")
        yield Select(
            [(z, z) for z in tab["timezones"]] + [(t("free value…"), FREE)],
            value=(tab["timezones"][0] if tab["timezones"] else null),
            allow_blank=False,
            id="f_tz_sel",
        )
        yield Input(
            value=tab["timezone"],
            placeholder=t("Timezone for the VMs"),
            id="f_tz",
            classes="freeval",
        )

    def compose_python(self):
        """mise pose un CPython PRÉCOMPILÉ, pyenv le COMPILE. Grisé quand
        aucune des VM retenues n'est sur une architecture que mise sert."""
        from textual.widgets import RadioButton, RadioSet, Static

        yield Static(
            t("Python interpreter:"), id="t_python", classes="grouptitle"
        )
        with RadioSet(id="f_python"):
            yield RadioButton(t("mise (precompiled, faster)"), value=True)
            yield RadioButton(t("pyenv (compiles from source)"))
        yield Static("", id="miswarn")

    # ------------------------------------------------------------------ #
    # Lire les widgets
    # ------------------------------------------------------------------ #
    def _widget(self, selector):
        """Le widget, ou None s'il n'est pas de cet écran."""
        try:
            return self.query_one(selector)
        except Exception:
            return None

    def _default_desktop(self) -> str:
        """« » pour un serveur, sinon la clé de la saveur choisie. Chaque
        rangée du plan peut s'en écarter."""
        desktops = self._extras["desktops"]
        widget = self._widget("#f_type")
        if widget is None:
            return ""
        index = widget.pressed_index
        if index is None or index < 1 or index > len(desktops):
            return ""
        return desktops[index - 1][0]

    def _install_state(self):
        """(une installation ?, quelque chose à installer ?).

        Deux réponses et non une : sans installation mais avec un bureau, il
        se pose encore des paquets — le magasin d'applications et les outils
        de la phase « avant » gardent un effet."""
        widget = self._widget("#f_install")
        installe = True if widget is None else bool(widget.value)
        return installe, bool(installe or self._default_desktop())

    def _vm_tools(self) -> tuple:
        """Clés des outils cochés, dans l'ordre de la liste."""
        picked = []
        for key, _label, _hint in self._extras["vm_tools"]:
            widget = self._widget(f"#f_tool_{key}")
            if widget is not None and widget.value:
                picked.append(key)
        return tuple(picked)

    def _tools_for_vm(self, vm, tools) -> list:
        return tools_for_vm(vm, tools, self._extras)

    def _app_store_needed(self) -> bool:
        return app_store_needed(self.vms, self._extras)

    def _app_store(self) -> str:
        """Magasin retenu. Sans VM concernée, la réponse est « deb » : elle
        ne change rien, et laisser passer « snap » réactiverait snapd pour
        rien."""
        stores = self._extras["app_stores"]
        widget = self._widget("#f_store")
        if not stores or widget is None or not self._app_store_needed():
            return "deb"
        index = widget.pressed_index
        if index is None or not (0 <= index < len(stores)):
            return stores[0][0]
        return stores[index][0]

    def _mise_usable(self) -> bool:
        return mise_usable(self.vms, self._extras)

    def _python_provider(self) -> str:
        """« mise », « pyenv », ou rien — c'est-à-dire « automatique ».

        Rien, et surtout pas « pyenv », quand mise n'est servi par aucune
        architecture retenue. « mise est indisponible » ne veut pas dire
        « l'utilisateur exige pyenv » : la nuance décide de tout, puisqu'un
        choix EXPLICITE écarte le Python de la distribution. Sur s390x,
        renvoyer « pyenv » forçait la compilation de CPython — celle dont gcc
        15.2 ne revient pas."""
        widget = self._widget("#f_python")
        if widget is None or not self._mise_usable():
            return ""
        return "pyenv" if widget.pressed_index == 1 else "mise"

    def _timezone(self) -> str:
        """Le fuseau des VM. Un champ vidé retombe sur celui de l'hôte plutôt
        que sur rien : sans valeur, la VM démarrerait en UTC."""
        widget = self._widget("#f_tz")
        saisi = widget.value.strip() if widget is not None else ""
        return saisi or self._extras["timezone"]

    def _extras_disk_gb(self, vm, tools) -> int:
        return extras_disk_gb(vm, tools, self._extras)

    # ------------------------------------------------------------------ #
    # Redessiner
    # ------------------------------------------------------------------ #
    def _render_store(self) -> None:
        """Grise le choix quand aucune VM ne le concerne, et dit pourquoi."""
        widget = self._widget("#f_store")
        if widget is None:
            return
        needed = self._app_store_needed()
        _installe, quelque_chose = self._install_state()
        widget.disabled = not (needed and quelque_chose)
        note = self._widget("#storewarn")
        if note is not None:
            note.update(
                ""
                if needed
                else f"  {t('No graphical VM on a snap-based distro.')}"
            )

    def _render_tools(self) -> None:
        """Grise chaque case qu'AUCUNE VM retenue ne peut recevoir, et NOMME
        ce qui sera écarté.

        Une case par outil, et non un blocage en bloc : sur un parc de
        serveurs les IDE se grisent, la compilation mobile reste offerte.
        Cocher Android Studio sur un parc ARM ne produit rien — le dire ici
        évite de le découvrir dans le journal d'installation."""
        tab = self._extras
        if not tab["vm_tools"]:
            return
        installe, quelque_chose = self._install_state()
        for key, _label, _hint in tab["vm_tools"]:
            widget = self._widget(f"#f_tool_{key}")
            if widget is None:
                continue
            usable = any(self._tools_for_vm(vm, (key,)) for vm in self.vms)
            # Un outil de la phase « après » vit DANS le dépôt ERPLibre :
            # sans installation, il n'a rien où s'installer, bureau ou pas.
            offert = (
                installe
                if tab["tool_phases"].get(key) == "after"
                else quelque_chose
            )
            widget.disabled = not (usable and offert)
        picked = self._vm_tools()
        skipped = sorted(
            {
                vm["name"]
                for vm in self.vms
                for k in picked
                if k not in self._tools_for_vm(vm, picked)
            }
        )
        note = self._widget("#toolwarn")
        if note is not None:
            note.update(
                f"  ⚠ {t('Partly skipped (arch or desktop):')} "
                f"{', '.join(skipped)}"
                if skipped
                else ""
            )

    def _render_mise(self) -> None:
        """Grise le choix quand aucune VM retenue n'est servie par mise, ou
        quand rien ne s'installe, et NOMME les architectures qui retomberont
        sur pyenv."""
        widget = self._widget("#f_python")
        if widget is None:
            return
        installe, _quelque_chose = self._install_state()
        widget.disabled = not (self._mise_usable() and installe)
        ecartees = sorted(
            {
                vm["arch"]
                for vm in self.vms
                if vm.get("arch") not in self._extras["mise_arches"]
            }
        )
        note = self._widget("#miswarn")
        if note is not None:
            note.update(
                f"  ⚠ {t('mise has no binary for:')} "
                f"{', '.join(ecartees)} — {t('those VMs use pyenv')}"
                if ecartees
                else ""
            )

    def render_extras(self) -> None:
        """Les trois, dans l'ordre. Appelée à la fin de chaque recalcul."""
        self._render_mise()
        self._render_store()
        self._render_tools()

    def _sync_install_deps(self) -> None:
        """Grise ce que le choix d'installation rend SANS EFFET.

        Trois états et non deux, parce que la commande distante en a trois :
        rien du tout, un bureau seul, ou une installation complète. Sans
        installation MAIS avec un bureau, le magasin d'applications et les
        outils de la phase « avant » servent encore — les griser mentirait
        autant que de laisser actif ce qui ne fait rien. La branche, le
        profil et l'interpréteur Python, eux, ne servent qu'à l'installation.

        Le type de VM et le suivi ne sont jamais grisés : le premier est
        l'autre moitié de la décision, le second regarde la VM arriver même
        quand rien ne s'installe."""
        installe, quelque_chose = self._install_state()
        for cible, actif in (
            ("#f_branch", installe),
            ("#f_profile_install", installe),
            ("#f_prod", quelque_chose),
        ):
            widget = self._widget(cible)
            if widget is not None:
                widget.disabled = not actif
        # Le magasin, les outils et l'interpréteur Python ont leur PROPRE
        # raison de se griser (architecture, bureau, distribution) : ils
        # composent les deux dans « _render_* », qui a le dernier mot.
        # Le titre suit ses champs : une section entière se lit inactive d'un
        # coup d'œil, au lieu de se déduire de trois widgets ternes.
        for cible, actif in (
            ("#t_store", quelque_chose),
            ("#t_tools", quelque_chose),
            ("#t_python", installe),
        ):
            widget = self._widget(cible)
            if widget is not None:
                widget.set_class(not actif, "off")
        # Les rangées portent les mêmes choix, par VM.
        for i in range(len(getattr(self, "rows", ()))):
            for cible in (f"#v{i}_branch", f"#v{i}_prof"):
                widget = self._widget(cible)
                if widget is not None:
                    widget.disabled = not installe

    # ------------------------------------------------------------------ #
    # Les messages, et la spec
    # ------------------------------------------------------------------ #
    def extras_on_select(self, event) -> bool:
        """Traite le sélecteur de fuseau. Rend True quand c'est fait, pour
        que l'appelant s'arrête là.

        « libre… » révèle la saisie ; un fuseau choisi la referme et y
        recopie le nom, seule valeur que lit `extras_values` — un seul
        endroit porte la réponse."""
        if getattr(event.select, "id", "") != "f_tz_sel":
            return False
        free = event.value is FREE
        field = self._widget("#f_tz")
        if field is None:
            return True
        field.display = free
        field.disabled = not free
        if free:
            field.focus()
        elif isinstance(event.value, str):
            field.value = event.value
        return True

    def extras_values(self) -> dict:
        """Le fragment de spec que ces réglages produisent."""
        return {
            "timezone": self._timezone(),
            "desktop": self._default_desktop(),
            "vm_tools": self._vm_tools(),
            "python_provider": self._python_provider(),
            "app_store": self._app_store(),
        }
