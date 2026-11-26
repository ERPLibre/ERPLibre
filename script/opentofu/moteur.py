# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Interface commune des moteurs de parc et plan indépendant du moteur.

Un moteur (`tofu` aujourd'hui, un autre demain) implémente `Moteur`; le menu
et le TUI ne parlent qu'à cette interface. Les moteurs s'enregistrent par
nom avec `enregistrer`, `moteur_pour` choisit celui que la spec demande.
Un `Changement` décrit ce que le moteur ferait à une VM; `formater_plan` le
rend en lignes traduites et `est_destructeur` dit si une confirmation
s'impose avant d'appliquer.
"""

import abc
import importlib
from dataclasses import dataclass, field

from script.todo.todo_i18n import t

ACTIONS = ("creer", "modifier", "remplacer", "detruire")
# Genres de ressource d'un `Changement` : la VM elle-même, son fichier
# cloud-init, l'image disque qu'elle importe.
RESSOURCE_VM = "vm"
RESSOURCE_CLOUD_INIT = "cloud-init"
RESSOURCE_IMAGE = "image"


@dataclass
class Changement:
    """Une action sur une ressource de VM, avec ses champs modifiés
    (`champ`, avant, après)."""

    action: str
    vm: str
    ressource: str
    details: list = field(default_factory=list)

    def __post_init__(self):
        if self.action not in ACTIONS:
            raise ValueError(f"action inconnue : {self.action!r}")


@dataclass
class Resultat:
    """Issue d'une opération : succès, message affichable, code de sortie."""

    ok: bool
    message: str = ""
    code: int = 0


class Moteur(abc.ABC):
    """Contrat d'un moteur. `journal` est un appelable `str -> None` qui
    reçoit chaque ligne de sortie, déjà expurgée des secrets."""

    nom: str = ""

    def __init__(self, racine=None, executer=None, **kw):
        """Tout moteur accepte ces deux mots-clés, que `moteur_pour` relaie.

        `racine` : dossier des parcs (None : celui du moteur). `executer` :
        exécuteur `cmd -> (code, sortie)` des commandes de l'hôte, élévation
        comprise (None : le moteur le bâtit depuis la spec). Les autres
        mots-clés sont propres à chaque moteur.
        """
        self.racine = racine
        self.executer = executer

    @abc.abstractmethod
    def disponible(self):
        """Rend `(ok, raison)` : le moteur peut-il tourner ici."""

    @abc.abstractmethod
    def preparer(self, spec):
        """Installe ce qu'il faut avant un plan; rend un `Resultat`."""

    @abc.abstractmethod
    def planifier(self, spec, journal):
        """Rend `(Resultat, [Changement])` sans toucher au parc.

        Effet de bord : les champs vides que la résolution remplit sont
        écrits dans le dict `spec` reçu, en place, et la spec résolue est
        sauvée ; l'appelant affiche et réutilise ces valeurs.
        """

    @abc.abstractmethod
    def appliquer(self, spec, journal):
        """Fait converger le parc vers la spec."""

    @abc.abstractmethod
    def detruire(self, spec, journal):
        """Détruit tout ce que le moteur gère pour ce parc."""

    @abc.abstractmethod
    def etat(self, spec):
        """Rend les lignes décrivant l'état connu du parc."""

    @abc.abstractmethod
    def sorties(self, spec):
        """Rend, par VM, `{"vmid": int, "ip": str}`."""


_REGISTRE = {}
# Moteurs livrés : leur module s'importe au premier `moteur_pour`, et
# s'enregistre lui-même à l'import.
_CONNUS = {"tofu": "script.opentofu.moteur_tofu"}


def enregistrer(nom, classe):
    """Associe un nom de moteur à sa classe."""
    _REGISTRE[nom] = classe


def moteurs_connus():
    """Noms des moteurs qu'une spec peut demander : livrés ou enregistrés."""
    return set(_CONNUS) | set(_REGISTRE)


def moteur_pour(spec, **kw):
    """Instancie le moteur que `spec["moteur"]` désigne, avec `**kw`.

    Un moteur livré mais pas encore importé l'est ici. Lève `KeyError`
    (message traduit) si ce nom n'est ni enregistré ni livré."""
    nom = spec.get("moteur")
    if nom not in _REGISTRE and nom in _CONNUS:
        importlib.import_module(_CONNUS[nom])
    if nom not in _REGISTRE:
        raise KeyError(t("Unknown engine: {nom}.").format(nom=nom))
    return _REGISTRE[nom](**kw)


def formater_plan(changements):
    """Une ligne par changement, puis une ligne indentée par détail."""
    if not changements:
        return [t("No changes.")]
    modeles = {
        "creer": t("+ create {vm} ({ressource})"),
        "modifier": t("~ modify {vm} ({ressource})"),
        "remplacer": t("± replace {vm} ({ressource})"),
        "detruire": t("- destroy {vm} ({ressource})"),
    }
    detail = t("    {champ} : {avant} → {apres}")
    lignes = []
    for c in changements:
        lignes.append(modeles[c.action].format(vm=c.vm, ressource=c.ressource))
        for champ, avant, apres in c.details:
            lignes.append(detail.format(champ=champ, avant=avant, apres=apres))
    return lignes


def est_destructeur(changements):
    """Vrai si le plan remplace ou détruit au moins une ressource."""
    return any(c.action in ("remplacer", "detruire") for c in changements)
