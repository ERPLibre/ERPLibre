#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Les étapes de la démonstration, et rien d'autre.

Ce module ne sait pas EXÉCUTER une étape : il décrit lesquelles existent,
dans quel ordre, laquelle est prête, et comment afficher le tout. C'est ce
qui permet au menu en ligne et au tableau de bord de partager exactement la
même vérité — deux vues d'un même état plutôt que deux implémentations qui
divergeront.

Aucune dépendance à Textual, à QEMU ni à `todo.py` : ce fichier se teste en
une milliseconde.
"""
from __future__ import annotations

from dataclasses import dataclass

try:
    from script.todo.todo_i18n import t
except Exception:  # pragma: no cover - repli si i18n indisponible

    def t(key: str) -> str:
        return key


#: Les quatre états qu'une étape peut prendre, et leur icône.
#:
#: Le tableau de bord d'installation QEMU utilise ⏳ pour « en attente » ET
#: pour « en cours ». On s'en écarte volontairement : sur un suivi d'étapes,
#: ne pas distinguer ce qui travaille de ce qui patiente rend le tableau
#: inutile au moment précis où on le regarde — quand quelque chose tarde.
ICON = {
    "pending": "○",
    "running": "⏳",
    "done": "✅",
    "failed": "❌",
}

STATE_PENDING = "pending"
STATE_RUNNING = "running"
STATE_DONE = "done"
STATE_FAILED = "failed"


@dataclass(frozen=True)
class Step:
    """Une étape de la démonstration.

    `manual` distingue ce que la machine fait seule de ce qui exige un
    humain et son téléphone. La distinction compte : une étape manuelle qui
    reste en attente n'est pas une panne, alors qu'une étape automatique
    bloquée en est une.
    """

    id: str
    label_key: str
    #: Libelle de rechange en mode local, quand l'etape ne fait pas la meme
    #: chose. Vide veut dire « le meme dans les deux modes ».
    label_key_local: str = ""
    manual: bool = False
    #: Étapes qui doivent être terminées avant que celle-ci ait un sens.
    requires: tuple = ()

    @property
    def label(self) -> str:
        return t(self.label_key)

    def label_for(self, mode: str) -> str:
        """Le libelle a afficher pour ce mode."""
        if mode == "local" and self.label_key_local:
            return t(self.label_key_local)
        return t(self.label_key)


STEPS = (
    Step("vm", "sms_step_vm", label_key_local="sms_step_env"),
    Step("odoo", "sms_step_odoo", requires=("vm",)),
    Step("gateway", "sms_step_gateway", requires=("vm", "odoo")),
    Step("mobile", "sms_step_mobile", manual=True, requires=("gateway",)),
    Step("verify", "sms_step_verify", requires=("gateway",)),
    Step("confirm", "sms_step_confirm", requires=("verify",)),
)

BY_ID = {s.id: s for s in STEPS}


def status_of(step: Step, state, running: str = "") -> str:
    """L'état d'une étape, du point de vue de l'état persisté."""
    if running == step.id:
        return STATE_RUNNING
    if step.id in getattr(state, "errors", {}):
        return STATE_FAILED
    if state.is_done(step.id):
        return STATE_DONE
    return STATE_PENDING


def blocked_by(step: Step, state) -> tuple:
    """Les prérequis manquants — vide si l'étape peut être lancée.

    Lancer une étape dont les prérequis manquent produit une erreur illisible
    au fond d'un journal SSH. Mieux vaut refuser tôt et dire laquelle manque.
    """
    return tuple(
        BY_ID[dep].label_for(state.spec.mode)
        for dep in step.requires
        if not state.is_done(dep)
    )


def next_step(state):
    """La prochaine étape à jouer, ou None si tout est fait.

    Une étape en échec est proposée AVANT les suivantes : reprendre là où ça
    a cassé est presque toujours ce qu'on veut, et enchaîner par-dessus une
    étape ratée ne produirait qu'un second échec moins compréhensible.
    """
    for step in STEPS:
        if step.id in state.errors:
            return step
    for step in STEPS:
        if not state.is_done(step.id):
            return step
    return None


def progress(state) -> tuple:
    """(terminées, total) — pour un résumé d'une ligne."""
    return sum(1 for s in STEPS if state.is_done(s.id)), len(STEPS)


def render(state, running: str = "") -> str:
    """Le tableau d'état, tel qu'affiché en ligne de commande.

    Même contenu que le tableau de bord, en texte : c'est ce qu'on copie
    dans un rapport de panne, et ce qui reste lisible quand Textual n'est
    pas installé.
    """
    fait, total = progress(state)
    lignes = [f"  {t('sms_status')} — {fait}/{total}", ""]
    for index, step in enumerate(STEPS, start=1):
        etat = status_of(step, state, running)
        marque = ICON[etat]
        suffixe = ""
        if etat == STATE_FAILED:
            suffixe = f"  ← {state.errors.get(step.id, '')[:60]}"
        elif step.manual and etat == STATE_PENDING:
            suffixe = f"  ({t('sms_manual_hint')})"
        libelle = step.label_for(state.spec.mode)
        lignes.append(f"  {marque} [{index}] {libelle}{suffixe}")
    if state.vm_ip:
        lignes += ["", f"  {t('sms_vm_address')} : {state.vm_ip}"]
    return "\n".join(lignes)
