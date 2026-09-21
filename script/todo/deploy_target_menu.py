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

from script.remote import deploy_target, host_memory, host_probe
from script.todo import deploy_verify
from script.todo import devstack_report as R
from script.todo.todo_i18n import t

# Le nom court du produit, pour le libellé d'une fiche déjà sondée.
PRODUIT = "ERPLibre"

# Ce que la SONDE dépose, et que personne ne saisit. Nommé plutôt que laissé
# implicite : c'est la SEULE raison admise pour qu'une clé de
# `deploy_target.DEFAULTS` manque au formulaire, et un garde dérivé s'appuie
# dessus pour réclamer toutes les autres. Une liste écrite en prose dans un
# commentaire en avait déjà oublié une sans que rien ne le dise.
CHAMPS_SONDE = ("verdict", "version", "sudo", "last_probe")

# Les champs du formulaire, dans l'ordre où on les demande. Le genre vient en
# deuxième parce qu'il décide de ce que les suivants VEULENT DIRE ; ensuite
# joindre la machine, ce qu'on y installe, ce qu'elle sert.
CHAMPS = (
    ("name", "Target name (lowercase, digits, - or _)"),
    ("kind", "What the target is for"),
    ("target", "Address: user@host, or a ~/.ssh/config alias"),
    ("jump", "Jump host (empty: connect directly)"),
    ("port", "SSH port (empty: let ssh decide)"),
    ("identity", "Private key path (empty: ~/.ssh/config decides)"),
    ("path", "Remote path where ERPLibre lives"),
    ("domain", "Domain served over HTTPS (empty: not served)"),
    ("admin_email", "Admin email for the certificate"),
)

# Ce que chaque genre veut dire pour qui remplit la fiche. Le nom technique
# ne le dit pas : « backup-ssh » tait que la cible REÇOIT, et prendre l'une
# pour l'autre déploierait ERPLibre sur le dépôt d'archives.
#
# La table est interrogée SANS défaut : un genre ajouté à
# `deploy_target.KINDS` et oublié ici lève, là où une explication vide se
# serait affichée sans que personne ne la réclame.
GENRES = {
    deploy_target.KIND_SSH: "ERPLibre is installed and served there",
    deploy_target.KIND_BACKUP: "it RECEIVES the backup archives",
}


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
                # LE GENRE SE VOIT. Deux fiches au même format, sur le même
                # transport, ne se distinguent que par lui ; les confondre
                # ferait déployer ERPLibre sur le dépôt d'archives.
                genre = deploy_target.with_defaults(cible)["kind"]
                suffixe = (
                    ""
                    if genre == deploy_target.KIND_SSH
                    else f" — {t(GENRES[genre])}"
                )
                print(f"   [{rang}] {libelle}{suffixe}{marque}")
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

    def _deploy_ssh_probe(self):
        """Sonde la cible retenue, dit ce qui tient, et l'écrit sur la fiche.

        Le privilège est CONSTATÉ et non exigé : neuf verbes sur onze s'en
        passent, et refuser la machine pour les deux autres les fermerait
        tous. Ce qui est constaté vit avec la fiche, pour que rouvrir l'écran
        sans re-sonder puisse dire ce qu'on savait, et depuis quand.
        """
        cible = deploy_target.selected()
        if cible is None:
            self._deploy_ssh_targets()
            cible = deploy_target.selected()
        if cible is None:
            return
        print(f"\n  {t('Checking')} {cible['target']}…")
        verdict = host_probe.diagnose(
            deploy_target.fiche(cible),
            deploy_target.probe_command(cible["path"]),
            deploy_target.parse_version,
            privilege=host_probe.OPTIONAL,
        )
        verdicts = deploy_verify.probe_layers(verdict)
        print(R.render_layers(verdicts))
        print(R.report(R.aggregate_layers(verdicts)))
        try:
            deploy_target.record_probe(cible, verdict)
        except deploy_target.ValidationError as erreur:
            print(f"✗ {t('Target refused: ')}{erreur}")

    @staticmethod
    def _deploy_target_choose(cibles, reponse):
        """Retient la cible que ce numéro désigne, ou le dit."""
        rang = _rang(reponse, len(cibles))
        if rang is None:
            print(t("Command not found !"))
            return
        cible = deploy_target.with_defaults(cibles[rang - 1])
        if cible["kind"] != deploy_target.KIND_SSH:
            # ON NOMME, ON N'EFFACE PAS. `selected()` refuse déjà cette
            # cible ; retenir sans le dire laisserait l'écran sans « ← » et
            # sans raison, et on croirait avoir choisi.
            print(
                f"✗ {t('Not a deployment target:')} {cible['name']}"
                f" — {t(GENRES[cible['kind']])}"
            )
            return
        deploy_target.select(cible["name"])

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
            if cle == "kind":
                brouillon[cle] = _demander_genre(brouillon.get(cle, ""))
                continue
            brouillon[cle] = _demander(t(libelle), brouillon.get(cle, ""))
        try:
            ecrite = deploy_target.save(brouillon)
        except deploy_target.ValidationError as erreur:
            print(f"\n✗ {t('Target refused: ')}{erreur}")
            return
        print(f"\n✓ {t('Target saved: ')}{ecrite['name']}")
        self._deploy_target_after_save(nom, ecrite)

    @staticmethod
    def _deploy_target_after_save(ancien, ecrite):
        """Suit le renommage, et retient la première cible de DÉPLOIEMENT.

        Écrire sous un nom neuf SANS retirer l'ancien laisserait la même
        machine deux fois dans l'inventaire, et la sélection sur celle qu'on
        croyait avoir quittée.

        Une cible de sauvegarde n'est jamais retenue : `selected()` la refuse,
        et annoncer « elle devient la cible retenue » sur une cible que le
        reste de l'écran ne verra JAMAIS retenue serait un message faux.
        """
        nouveau = ecrite["name"]
        deployable = ecrite.get("kind") == deploy_target.KIND_SSH
        retenue = deploy_target.selected()
        if ancien and ancien != nouveau:
            deploy_target.delete(ancien)
            if retenue is None or retenue["name"] == ancien:
                if deployable:
                    deploy_target.select(nouveau)
                return
        if deployable and deploy_target.selected() is None:
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


def _demander_genre(defaut):
    """Le genre de la cible, choisi par NUMÉRO parmi ceux que le code connaît.

    Rend un membre de `deploy_target.KINDS`, toujours. Tapé en toutes lettres,
    « backup-ssh » se saisit mal et n'est refusé qu'à l'écriture, la fiche
    entière déjà ressaisie ; un numéro ne peut désigner qu'un genre existant.

    Vide garde celui en place, comme partout dans ce formulaire. Une réponse
    qui ne désigne rien est DITE et redemandée : retomber sur le défaut
    poserait une cible de déploiement là où on voulait une cible de
    sauvegarde, et les deux se ressemblent trop dans la liste pour qu'on le
    remarque.
    """
    genres = list(deploy_target.KINDS)
    courant = defaut if defaut in genres else deploy_target.KIND_SSH
    print(f"\n   {t('What the target is for')} :")
    for rang, genre in enumerate(genres, 1):
        marque = " ←" if genre == courant else ""
        print(f"   [{rang}] {genre} — {t(GENRES[genre])}{marque}")
    while True:
        reponse = input(f"   [1-{len(genres)}] [{courant}] : ").strip()
        if not reponse:
            return courant
        rang = _rang(reponse, len(genres))
        if rang:
            return genres[rang - 1]
        print(f"   ✗ {t('Command not found !')}")
