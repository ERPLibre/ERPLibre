#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""L'écran des cibles de déploiement : choisir, ajouter, modifier, effacer.

La frontière avec `script/remote/deploy_target.py` est nette : ici on DEMANDE
et on affiche, là-bas on valide et on écrit. Ce fichier ne connaît ni le
format du fichier de configuration, ni les motifs de validation, ni où
l'inventaire est rangé.

Les cibles se choisissent par NUMÉRO, les actions par LETTRE. Deux listes
numérotées qui se suivent invitent à retaper le numéro de la précédente ; la
lettre dit « autre question ».
"""

from script.remote import deploy_target, host_memory
from script.todo.todo_i18n import t

# Le nom court du produit, pour le libellé d'une fiche déjà sondée.
PRODUIT = "ERPLibre"

# Les champs du formulaire, dans l'ordre où on les demande : d'abord joindre
# la machine, ensuite ce qu'on y installe, enfin ce qu'elle sert. Les champs
# que la sonde dépose — verdict, version, date — ne se saisissent pas.
CHAMPS = (
    ("name", "Target name (lowercase, digits, - or _)"),
    ("target", "Address: user@host, or a ~/.ssh/config alias"),
    ("jump", "Jump host (empty: connect directly)"),
    ("port", "SSH port (empty: let ssh decide)"),
    ("identity", "Private key path (empty: ~/.ssh/config decides)"),
    ("path", "Remote path where ERPLibre lives"),
    ("domain", "Domain served over HTTPS (empty: not served)"),
    ("admin_email", "Admin email for the certificate"),
)


class DeployTargetMenuMixin:
    """L'écran de choix, greffé sur le menu Deploy › SSH."""

    def _deploy_ssh_targets(self):
        """Liste les cibles, et laisse en choisir, ajouter ou retirer une."""
        while True:
            cibles = deploy_target.load_all()
            retenue = deploy_target.selected()
            nom_retenu = retenue["name"] if retenue else ""
            print(f"\n🎯 {t('Deployment targets')}")
            if not cibles:
                print(f"   {t('None yet: [a] adds the first one.')}")
            for rang, cible in enumerate(cibles, 1):
                marque = " ←" if cible.get("name") == nom_retenu else ""
                libelle = host_memory.label(
                    deploy_target.fiche(cible), PRODUIT
                )
                print(f"   [{rang}] {libelle}{marque}")
            print(
                f"\n   [a] {t('Add')}   [m] {t('Edit')}   [s] {t('Delete')}"
                f"   [o] {t('Forget the selection')}   [0] {t('Back')}"
            )
            reponse = input("> ").strip().lower()
            if reponse == "0":
                return
            if reponse == "a":
                self._deploy_target_edit("")
            elif reponse == "m":
                self._deploy_target_edit(self._deploy_target_pick(cibles))
            elif reponse == "s":
                self._deploy_target_delete(cibles)
            elif reponse == "o":
                deploy_target.select("")
                print(f"✓ {t('Selection forgotten.')}")
            elif reponse:
                self._deploy_target_choose(cibles, reponse)

    @staticmethod
    def _deploy_target_choose(cibles, reponse):
        """Retient la cible que ce numéro désigne, ou le dit."""
        rang = _rang(reponse, len(cibles))
        if rang is None:
            print(t("Command not found !"))
            return
        deploy_target.select(cibles[rang - 1]["name"])

    @staticmethod
    def _deploy_target_pick(cibles):
        """Le nom que désigne un numéro, ou « » si personne ne le désigne.

        Ne réaffiche pas la liste : elle est juste au-dessus, et la
        renuméroter ailleurs ferait taper le mauvais rang.
        """
        if not cibles:
            print(t("Command not found !"))
            return ""
        reponse = input(f"{t('Which target?')} [1-{len(cibles)}] : ").strip()
        rang = _rang(reponse, len(cibles))
        return cibles[rang - 1]["name"] if rang else ""

    def _deploy_target_edit(self, nom):
        """Crée une cible, ou modifie celle qui porte ce nom.

        Une réponse vide garde la valeur en place : corriger un seul champ ne
        doit pas obliger à ressaisir les sept autres.
        """
        if nom == "":
            courante = {}
        else:
            courante = deploy_target.load(nom)
            if courante is None:
                return
        brouillon = deploy_target.with_defaults(courante)
        for cle, libelle in CHAMPS:
            brouillon[cle] = _demander(t(libelle), brouillon.get(cle, ""))
        try:
            ecrite = deploy_target.save(brouillon)
        except deploy_target.ValidationError as erreur:
            print(f"\n✗ {t('Target refused: ')}{erreur}")
            return
        print(f"\n✓ {t('Target saved: ')}{ecrite['name']}")
        self._deploy_target_after_save(nom, ecrite["name"])

    @staticmethod
    def _deploy_target_after_save(ancien, nouveau):
        """Suit le renommage, et retient la première cible écrite.

        Écrire sous un nom neuf SANS retirer l'ancien laisserait la même
        machine deux fois dans l'inventaire, et la sélection sur celle qu'on
        croyait avoir quittée.
        """
        retenue = deploy_target.selected()
        if ancien and ancien != nouveau:
            deploy_target.delete(ancien)
            if retenue is None or retenue["name"] == ancien:
                deploy_target.select(nouveau)
                return
        if deploy_target.selected() is None:
            deploy_target.select(nouveau)
            print(f"  {t('It becomes the selected target.')}")

    def _deploy_target_delete(self, cibles):
        nom = self._deploy_target_pick(cibles)
        if not nom:
            return
        if not self._is_yes(
            input(f"{t('Delete target')} « {nom} » ? (y/N) : ")
        ):
            return
        if deploy_target.delete(nom):
            print(f"✓ {t('Target deleted.')}")
            return
        print(
            "✗ "
            + t(
                "Not deletable here: this target comes from a shared"
                " configuration file."
            )
        )


def _rang(reponse, combien):
    """Le rang que « reponse » désigne dans une liste de `combien`, ou None."""
    try:
        rang = int(reponse)
    except ValueError:
        return None
    return rang if 0 < rang <= combien else None


def _demander(libelle, defaut):
    """Question à réponse par défaut. Vide = on garde `defaut`."""
    montre = f" [{defaut}]" if defaut else ""
    return input(f"{libelle}{montre} : ").strip() or defaut
