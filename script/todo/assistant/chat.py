#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""La conversation : les tours, en mémoire, et les commandes qui la pilotent.

L'historique vit dans cet objet et NULLE PART ailleurs : rien ici n'ouvre un
fichier. Il meurt avec le menu, et `/save` — dont l'écriture appartient au
menu — est le seul moyen d'en garder une trace, ce qui doit se dire AVANT la
conversation qui méritait d'être gardée.

Deux subtilités que la forme de la boucle impose :

**`keeps_history`.** Une session `claude` tient son histoire de son côté. La
conversation demande donc au backend s'il la garde et, dans ce cas, n'envoie
que le nouveau tour : rejouer l'historique local doublerait chaque échange et
ferait payer deux fois les mêmes jetons.

**Toute commande porte une barre oblique initiale, et aucun nombre nu n'est
une commande.** Une question collée sur plusieurs lignes devient autant de
tours, et une ligne collée valant `0` déclencherait une action de menu si les
nombres décidaient. `parse_command` ne reconnaît donc qu'un mot d'une seule
barre oblique et rend tout le reste comme du texte.

Les valeurs de `COMMANDS` SONT les clés i18n : `t()` rend une clé absente
inchangée, donc une commande non traduite s'affiche en anglais correct. La
traduction se fait à l'affichage, dans le menu.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from script.todo.assistant.backends import BackendError, Interrupted

# La forme d'une commande : une barre oblique, puis des lettres ou « ? », et
# rien d'autre. Une seconde barre oblique fait de la ligne un chemin, et une
# question qui commence par un chemin reste une question.
COMMAND_SHAPE = re.compile(r"^/[a-z?]{1,12}$")

# L'ordre est celui de l'affichage de `/?` : partir, repartir, changer, voir.
COMMANDS: dict[str, str] = {
    "/q": "back to the menu",
    "/new": "clear the history (same server, same tool)",
    "/gpt": "change tool, history kept",
    "/srv": (
        "change server, history CLEARED — the model is no longer the same"
    ),
    "/ctx": "show again what was sent",
    "/m": 'multi-line entry, end with a single "." line',
    "/save": "write the conversation to a file",
    "/?": "list the commands",
}


@dataclass
class Turn:
    """Un tour : qui parle, ce qui a été dit, et si la réponse a été coupée.

    `role` vaut `user`, `assistant` ou `error`. Un tour `error` n'entre jamais
    dans l'historique : il rapporte une panne, pas un échange.
    """

    role: str
    text: str
    interrupted: bool = False


def parse_command(line: str) -> tuple[str | None, str]:
    """La commande d'une ligne saisie, et ce qui la suit.

    Rend `(None, line)` — la ligne INTACTE, collage compris — pour tout ce qui
    n'est pas de la forme d'une commande : l'appelant traite cela comme du
    texte à envoyer. Rend sinon `(commande, reste)`, la commande en
    minuscules ; l'appelant confronte la commande à `COMMANDS` et nomme
    celle qu'il ne connaît pas plutôt que de l'envoyer au modèle.
    """
    texte = (line or "").strip()
    if not texte.startswith("/"):
        return None, line
    tete, _, reste = texte.partition(" ")
    tete = tete.lower()
    if not COMMAND_SHAPE.match(tete):
        return None, line
    return tete, reste.strip()


class Conversation:
    """Les tours d'un échange avec un backend, en mémoire seulement.

    `system` prime sur celui du gpt, ce qui permet au menu de composer une
    invite système sans toucher au catalogue. `last_sent` porte les messages
    du dernier envoi — c'est ce que `/ctx` réaffiche, y compris après une
    panne, parce que ce qui est parti est parti.

    L'historique ne garde que les échanges qui portent du texte : une panne
    n'y laisse rien, et retaper la question EST la reprise.
    """

    def __init__(self, backend, *, gpt=None, system=None):
        self.backend = backend
        self.gpt = gpt
        if system is None:
            system = getattr(gpt, "system", "") or ""
        self.system = system
        self.turns: list[Turn] = []
        self.last_sent: list[dict] = []
        self.last_meta: dict = {}

    def _messages(self, text) -> list[dict]:
        """Les messages du prochain envoi.

        Un backend qui garde son histoire ne reçoit que le nouveau tour — ni
        l'historique, ni l'invite système, qu'il porte déjà de son côté.
        """
        if getattr(self.backend, "keeps_history", False):
            return [{"role": "user", "content": text}]
        messages = []
        if self.system:
            messages.append({"role": "system", "content": self.system})
        for tour in self.turns:
            messages.append({"role": tour.role, "content": tour.text})
        messages.append({"role": "user", "content": text})
        return messages

    def ask(self, text, *, on_chunk=None) -> Turn:
        """Un tour de conversation, et le tour rendu par le backend.

        Rend un tour `error` quand l'envoi échoue : le message tient sur une
        ligne et l'historique reste tel qu'il était. Une coupure rend un tour
        marqué `interrupted` et garde le texte déjà reçu — il a été payé.
        """
        question = Turn("user", text)
        messages = self._messages(text)
        self.last_sent = messages
        try:
            reponse, faits = self.backend.send(messages, on_chunk=on_chunk)
        except (Interrupted, KeyboardInterrupt) as coupure:
            partiel = getattr(coupure, "partial", "")
            self.last_meta = getattr(coupure, "meta", {}) or {}
            tour = Turn("assistant", partiel, interrupted=True)
            if partiel:
                self.turns.extend((question, tour))
            return tour
        except BackendError as panne:
            return Turn("error", str(panne))
        self.last_meta = faits or {}
        tour = Turn("assistant", reponse)
        self.turns.extend((question, tour))
        return tour

    def reset(self) -> int:
        """Vide l'historique et rend le nombre de tours jetés.

        Chaque question et chaque réponse compte pour un tour : un échange
        complet en vaut deux.
        """
        jetes = len(self.turns)
        self.turns = []
        self.last_sent = []
        self.last_meta = {}
        return jetes

    def transcript(self) -> str:
        """La conversation en Markdown, prête pour `/save`.

        Porte les tours et le nom du gpt, pas l'invite système : `/ctx`
        montre ce qui est parti, ce fichier montre ce qui s'est dit.
        """
        lignes = []
        nom = getattr(self.gpt, "name", "")
        if nom:
            lignes += [f"# {nom}", ""]
        for tour in self.turns:
            marque = " (interrupted)" if tour.interrupted else ""
            lignes += [f"## {tour.role}{marque}", tour.text, ""]
        return "\n".join(lignes)
