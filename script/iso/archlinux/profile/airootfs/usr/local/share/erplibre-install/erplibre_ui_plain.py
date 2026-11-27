#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Le mode texte de l'installateur : les mêmes questions que l'écran
Textual, posées ligne à ligne, pour une console série, un terminal
« dumb » ou une saisie automatisée (entrée standard qui n'est pas un
terminal).

Chaque réponse est vérifiée dès qu'elle est tapée, par
erplibre_ui_flow.collect() : une réponse refusée redemande le même
champ. Les secrets se lisent par `getpass` (sans écho) quand l'entrée
standard est un terminal ; sinon par la même lecture que le reste, sur
l'entrée standard : getpass lirait /dev/tty, le clavier de la console,
et une saisie automatisée attendrait à jamais ses phrases. Rien n'est
effacé sans le nom du disque retapé.

Entrées et sorties injectées (`read`, `secret`, `write`) : un test joue
une session entière avec une liste de réponses.
"""

import getpass
import subprocess
import sys

import erplibre_ui_flow as flow

# Réponses oui/non acceptées, en français comme en anglais.
YES = frozenset({"y", "yes", "o", "oui", "1"})
NO = frozenset({"n", "no", "non", "0"})


class Cancelled(Exception):
    """La saisie est close (fin de l'entrée) ou l'utilisateur annule."""


class PlainUI:
    """Une session du mode texte. session() rend (action, donnée, tr),
    l'action que le lanceur exécute : « todo », « archinstall » (donnée =
    clé du profil ERPLibre), « reboot », « shell »."""

    def __init__(
        self,
        ctx,
        tr,
        read=input,
        secret=None,
        write=print,
        run=subprocess.run,
        popen=subprocess.Popen,
        sleep=None,
        dry_run=False,
    ):
        self.ctx = ctx
        self.tr = tr
        self._read = read
        if secret is None:
            secret = getpass.getpass if _stdin_is_tty() else read
        self._secret = secret
        self.write = write
        self.run = run
        self.popen = popen
        self.sleep = sleep
        self.dry_run = dry_run

    # Saisie

    def read(self, invite):
        try:
            return self._read(invite)
        except EOFError as exc:
            raise Cancelled() from exc

    def read_secret(self, invite):
        try:
            return self._secret(invite)
        except EOFError as exc:
            raise Cancelled() from exc

    def yes_no(self, question, default=False):
        tr = self.tr
        suffixe = tr("[Y/n]") if default else tr("[y/N]")
        while True:
            reponse = self.read(f"{question} {suffixe} ").strip().lower()
            if not reponse:
                return default
            if reponse in YES:
                return True
            if reponse in NO:
                return False
            self.write(tr("Answer yes or no."))

    def choose(self, titre, choix, default=None):
        """La valeur choisie parmi `choix` [(valeur, libellé)] par son
        numéro ; Entrée garde `default` s'il y en a un."""
        tr = self.tr
        self.write(titre)
        for i, (valeur, libelle) in enumerate(choix, 1):
            marque = " *" if valeur == default else ""
            self.write(f"  [{i}] {libelle}{marque}")
        while True:
            reponse = self.read(tr("Choice: ")).strip()
            if not reponse and default is not None:
                return default
            if reponse.isdigit() and 1 <= int(reponse) <= len(choix):
                return choix[int(reponse) - 1][0]
            self.write(tr("Invalid choice."))

    # Accueil

    def session(self):
        try:
            return self._session()
        except (Cancelled, KeyboardInterrupt):
            self.write("")
            return "shell", None, self.tr

    def _session(self):
        while True:
            tr = self.tr
            self.write("")
            self.write(
                tr("ERPLibre installer — Arch Linux + GNOME + ERPLibre")
            )
            self.write(
                tr("Machine profile: {profile}", profile=self.profile_line())
            )
            etat = flow.live_status(self.run)
            self.write(self.status_line(etat))
            self.write(f"  [1] {tr('Install ERPLibre')}")
            self.write(f"  [2] {tr('Start ERPLibre TODO')}")
            self.write(f"  [3] {tr('Run archinstall (guided, pre-filled)')}")
            self.write(f"  [l] {tr('Français / English')}")
            self.write(f"  [r] {tr('Reboot')}")
            self.write(f"  [q] {tr('Quit to the shell')}")
            choix = self.read(tr("Choice: ")).strip().lower()
            if choix == "1":
                fin = self.install()
                if fin:
                    return fin, None, self.tr
            elif choix == "2":
                return "todo", None, self.tr
            elif choix == "3":
                cle = self.choose_erplibre()
                if cle:
                    return "archinstall", cle, self.tr
            elif choix == "l":
                self.tr = self.tr.toggled()
                self.ctx["lang"] = self.tr.lang
            elif choix == "r":
                return "reboot", None, self.tr
            elif choix == "q":
                return "shell", None, self.tr
            else:
                self.write(tr("Invalid choice."))

    def profile_line(self):
        if self.ctx.get("profile_error"):
            code, details = self.ctx["profile_error"]
            return flow.reason_message(self.tr, code, details)
        return flow.profile_title(self.ctx, self.tr)

    def status_line(self, etat):
        tr = self.tr
        reseau = tr("connected") if etat["network"] else tr("NOT connected")
        return tr("Network: {state}", state=reseau)

    def choose_erplibre(self):
        tr = self.tr
        choix = [(e["key"], e["label"]) for e in self.ctx["erplibre"]]
        if not choix:
            self.write(tr("No ERPLibre profile on this key."))
            return None
        return self.choose(
            tr("What should be installed with GNOME?"),
            choix,
            flow._default_erplibre(self.ctx),
        )

    # Installation

    def install(self):
        """Le formulaire, le récapitulatif, puis l'installation. Rend
        l'action de fin (« reboot », « shell ») ou None pour revenir à
        l'accueil."""
        tr = self.tr
        if not self.ctx.get("profile"):
            self.write(self.profile_line())
            return None
        valeurs = self.fill_form()
        doc, erreurs = flow.collect(self.ctx, valeurs, tr)
        if erreurs:
            for cle, message in erreurs:
                self.write(f"{cle}: {message}")
            return None
        avis = flow.review(self.ctx, doc, tr)
        if not avis["ok"]:
            for ligne in avis["messages"]:
                self.write(ligne)
            return None
        doc = self.confirm(doc, avis["prep"])
        if doc is None:
            self.write(tr("Cancelled: nothing was erased."))
            return None
        rc = self.execute(doc)
        return self.final(rc)

    def fill_form(self):
        """Les valeurs du formulaire, champ par champ, chacune vérifiée
        avant de passer à la suivante."""
        valeurs = {}
        self.write("")
        self.write(
            self.tr("Machine profile: {profile}", profile=self.profile_line())
        )
        champs = flow.form_fields(self.ctx, self.tr)
        par_cle = {c["key"]: c for c in champs}
        for champ in champs:
            if champ["key"] not in flow.visible(self.ctx, valeurs):
                continue
            while True:
                self.ask_until_valid(champ, valeurs)
                if champ["kind"] != "confirm" or not self.field_error(
                    champ["key"], valeurs
                ):
                    break
                # Deux saisies qui diffèrent : la faute peut être dans la
                # première, qui se retape aussi.
                self.ask_until_valid(par_cle[champ["of"]], valeurs)
            if champ["kind"] == "keymap":
                self.keymap_applied(valeurs["keymap"])
        return valeurs

    def ask_until_valid(self, champ, valeurs):
        """Redemande `champ` tant que sa réponse est refusée. Une
        confirmation refusée l'est parce qu'elle diffère : l'appelant
        fait alors retaper le secret avant elle."""
        while True:
            valeurs[champ["key"]] = self.ask(champ)
            refus = self.field_error(champ["key"], valeurs)
            if not refus:
                return
            self.write(f"  ! {refus}")
            if champ["kind"] == "confirm":
                return

    def field_error(self, cle, valeurs):
        _doc, erreurs = flow.collect(self.ctx, valeurs, self.tr)
        return next((m for c, m in erreurs if c == cle), None)

    def keymap_applied(self, nom):
        ok, erreur = flow.apply_keymap(nom, self.run)
        if ok:
            self.write(
                self.tr("Keyboard layout « {name} » applied.", name=nom)
            )
        else:
            self.write(
                self.tr(
                    "loadkeys {name} failed: {error}", name=nom, error=erreur
                )
            )

    def ask(self, champ):
        sorte = champ["kind"]
        libelle = champ["label"]
        defaut = champ.get("default")
        if sorte in ("secret", "confirm"):
            return self.read_secret(f"{libelle} : ")
        if sorte == "bool":
            return self.yes_no(libelle, bool(defaut))
        if sorte == "choice":
            return self.choose(libelle, champ["choices"], defaut)
        invite = f"{libelle} [{defaut}] : " if defaut else f"{libelle} : "
        reponse = self.read(invite).strip()
        return reponse or (defaut or "")

    def confirm(self, doc, prep):
        """Affiche le récapitulatif ; rend le document confirmé, ou None
        si le nom du disque n'est pas retapé.

        Le formatage NVMe se décide AVANT le récapitulatif : coché, il
        ajoute « nvme format » aux commandes et relève les secteurs LUKS à
        4096, et le récapitulatif montre ce plan-là, celui qui sera
        exécuté."""
        tr = self.tr
        vue = flow.recap(self.ctx, doc, prep, tr)
        nvme = False
        if vue["nvme_lbaf"] is not None:
            nvme = self.yes_no(
                tr(
                    "Reformat the NVMe disk to 4 KiB sectors (format {lbaf})?",
                    lbaf=vue["nvme_lbaf"],
                ),
                False,
            )
            if nvme:
                avis = flow.review(
                    self.ctx, flow.with_nvme_format(doc, True), tr
                )
                if not avis["ok"]:
                    for ligne in avis["messages"]:
                        self.write(ligne)
                    return None
                prep = avis["prep"]
                vue = flow.recap(self.ctx, doc, prep, tr)
        self.write("")
        self.write(tr("Summary — nothing is written yet"))
        self.write(tr("Machine profile: {profile}", profile=vue["profile"]))
        for libelle, valeur in vue["summary"]:
            self.write(f"  {libelle} : {valeur}")
        self.write(tr("Hardware"))
        for libelle, valeur in vue["hardware"]:
            self.write(f"  {libelle} : {valeur}")
        for alerte in vue["warnings"]:
            self.write(f"  ! {alerte}")
        self.write(tr("Commands"))
        for commande in vue["commands"]:
            self.write(f"  {commande}")
        self.write("")
        self.write(tr("ALL DATA ON THIS DISK WILL BE ERASED:"))
        self.write(f"  {vue['disk']}")
        for partition in vue["partitions"]:
            self.write(f"    {partition}")
        tape = self.read(
            tr(
                "Type « {name} » to erase it (Enter cancels): ",
                name=vue["expected"],
            )
        ).strip()
        if not tape or not flow.disk_confirmed(prep, tape):
            return None
        return flow.confirm_document(doc, tape, nvme, prep)

    def execute(self, doc):
        tr = self.tr
        attente = {"run": self.run, "network": flow.needs_network(doc)}
        if self.sleep is not None:
            attente["sleep"] = self.sleep
        if not self.dry_run and not flow.wait_ready(self.write, tr, **attente):
            return flow.NETWORK_EXIT
        self.write(tr("Installation started; it takes a while."))
        # L'entrée standard reste celle de la console : le cœur la voit
        # comme son terminal et l'étape ERPLibre y recopie sa sortie.
        return flow.run_core(
            self.ctx,
            doc,
            self.write,
            popen=self.popen,
            dry_run=self.dry_run,
            stdin=None,
        )

    def final(self, rc):
        tr = self.tr
        self.write("")
        self.write(flow.exit_message(tr, rc, self.dry_run))
        self.write(tr("Logs: {path}", path="/var/log/erplibre-install"))
        choix = [
            ("reboot", tr("Reboot")),
            ("shell", tr("Quit to the shell")),
            ("home", tr("Back to the home screen")),
        ]
        fin = self.choose(
            tr("What now?"), choix, "reboot" if rc == 0 else None
        )
        return None if fin == "home" else fin


def _stdin_is_tty():
    try:
        return sys.stdin is not None and sys.stdin.isatty()
    except (AttributeError, ValueError):
        return False


def ask_lines(read):
    """Un lecteur qui rend, appel après appel, les lignes d'une liste :
    sert aux tests et aux réponses écrites d'avance."""
    lignes = iter(read)

    def lire(_invite=""):
        try:
            return next(lignes)
        except StopIteration as exc:
            raise EOFError() from exc

    return lire
