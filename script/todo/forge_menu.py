#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Le menu de la forge : profils, jeton, et ce qu'elle répond.

La frontière avec `script/forge/` est nette : ici on DEMANDE (quel profil,
quelle adresse, quel jeton) et on affiche ; là-bas on décide et on appelle.
Ce fichier ne bâtit aucune URL et ne lit aucun code HTTP.

CHAQUE VERDICT A SA PHRASE, et la phrase dit QUOI FAIRE. Un verdict brut —
« bad-token » — laisse le lecteur deviner ; quatre pannes qui se ressemblent
se corrigent à quatre endroits différents, et c'est précisément là qu'un
message qui n'oriente pas coûte une heure.

LE JETON NE S'AFFICHE JAMAIS. Ni en écho de saisie, ni dans une liste, ni
dans un résumé de profil : on dit qu'il est là, pas ce qu'il vaut. Un menu
se déroule souvent devant quelqu'un, et sa sortie se colle dans un rapport.
"""

import getpass
import glob
import os
from xml.etree import ElementTree

import click

from script.forge import mirror, profiles
from script.forge.api import ForgeClient
from script.forge import api
from script.lib_valid import ValidationError
from script.todo.todo_i18n import t
from script.vault.store import SecretError, SecretStore

# Le manifeste du CHECKOUT : ce que le poste utilise vraiment, et ce à
# quoi trois autres scripts du dépôt défaultent déjà.
MANIFEST_DEFAULT = ".repo/local_manifests/erplibre_manifest.xml"

# Ce qu'on écrit pour chaque verdict, et QUOI FAIRE ensuite. La table est
# exhaustive : `verdict_sentence` refuse un verdict qu'elle ne connaît pas
# plutôt que de rendre une chaîne vide, qui s'afficherait comme un succès.
SENTENCES = {
    api.OK: "Forge reached.",
    api.NO_TOKEN: (
        "No API token for this profile. Store one with « Store the API"
        " token »; create it in the forge under Settings > Applications."
    ),
    api.BAD_TOKEN: (
        "The forge refused the token. Check it has not expired, and that it"
        " carries the scopes the operation needs."
    ),
    api.LOCALNETWORK_REFUSED: (
        "The forge refuses a private-range target. This is its"
        " ALLOW_LOCALNETWORKS setting, NOT the token: regenerating a token"
        " changes nothing. Set FORGEJO_ALLOW_LOCALNETWORKS=1 and reinstall,"
        " or edit [migrations] in /etc/forgejo/app.ini."
    ),
    api.NOT_FOUND: "Nothing at that address on the forge.",
    api.ALREADY_EXISTS: "It already exists on the forge.",
    api.TLS_UNTRUSTED: (
        "The certificate is not trusted. Trust the authority on this"
        " machine; turning verification off in the profile sends the token"
        " to whoever answers in the forge's place."
    ),
    api.UNREACHABLE: (
        "No answer from the forge. Check the address, the port, and that the"
        " service is running."
    ),
    api.REFUSED: "The forge refused the call.",
}


# Ce que chaque rôle veut dire. Le rôle VIDE en a une lui aussi : montré nu,
# il ne se distinguerait pas d'une question restée sans réponse, alors que
# l'atelier est un choix et non un défaut subi.
#
# Interrogée SANS défaut, comme SENTENCES : un rôle ajouté à
# `profiles.ROLES` et oublié ici lève, au lieu d'afficher une ligne vide qui
# se lirait comme un choix offert.
ROLES_DITS = {
    # `marque` est ce qu'une LIGNE DE LISTE porte, `phrase` ce que le
    # formulaire propose. La marque de l'atelier est vide : c'est le cas
    # ordinaire, et l'annoter chargerait toutes les lignes pour ne rien
    # distinguer. Les deux sont des CLÉS de traduction écrites en toutes
    # lettres — une clé fabriquée par découpe rendrait l'anglais en silence.
    "": {
        "marque": "",
        "phrase": "workshop: one works here, and what is laid here"
        " can be redone",
    },
    profiles.ROLE_CANONIQUE: {
        "marque": "AUTHORITY",
        "phrase": "authority: the one you start again from when the"
        " station burns",
    },
}

# Ce que chaque sens de miroir veut dire. « entrant » et « sortant » ne
# disent pas d'eux-mêmes QUI pousse, et se tromper de sens écrase chez un
# tiers ce qu'on en avait reçu.
#
# Interrogée SANS défaut, comme SENTENCES et ROLES_DITS : un sens ajouté à
# `mirror.SENS` et oublié ici lève, au lieu d'offrir un choix muet.
SENS_DITS = {
    mirror.ENTRANT: "inbound: it lives upstream, and the forge follows it",
    mirror.SORTANT: "outbound: it lives here, and goes out to be seen",
}

# Ce que le formulaire REPORTE sans le demander. Nommé plutôt que laissé
# implicite : c'est la seule raison admise pour qu'une clé de
# `profiles.DEFAULTS` ne soit pas une question, et un garde dérivé s'appuie
# dessus pour réclamer toutes les autres. Le pilote n'a qu'une valeur
# connue — une question à une seule réponse n'en est pas une.
CHAMPS_REPORTES = ("driver",)


def verdict_sentence(kind: str) -> str:
    """La phrase d'un verdict, traduite. Lève sur un verdict inconnu.

    Un `dict.get` rendant "" afficherait une ligne vide, qui se lit comme un
    succès. Un verdict ajouté au vocabulaire sans phrase doit se voir ici,
    pas se taire chez l'utilisateur.
    """
    if kind not in SENTENCES:
        raise KeyError(f"verdict sans phrase : {kind!r}")
    return t(SENTENCES[kind])


def profile_line(profile: dict, has_token: bool) -> str:
    """Une ligne de liste : ce qu'on voit d'un profil sans le déplier.

    Deux champs y figurent parce que leur oubli se paie en secret : une
    vérification TLS coupée ne se voit nulle part ailleurs, et une autorité
    perdue ne se voit qu'au geste qui la cherche et n'en trouve plus. Le
    jeton se dit PRÉSENT ou ABSENT, jamais en valeur.
    """
    marques = []
    role = str(profile.get("role") or "").strip()
    if ROLES_DITS[role]["marque"]:
        marques.append(t(ROLES_DITS[role]["marque"]))
    if not profile.get("verify_tls", True):
        marques.append(t("TLS UNVERIFIED"))
    if profile.get("allow_plaintext"):
        marques.append(t("PLAINTEXT"))
    marques.append(t("token stored") if has_token else t("no token"))
    return (
        f"{profile.get('name', '?')} — {profile.get('url', '?')}"
        f" ({profile.get('owner', '?')}) [{', '.join(marques)}]"
    )


class ForgeMenuMixin:
    # ------------------------------------------------------------------
    # Menu
    # ------------------------------------------------------------------
    def prompt_execute_forge(self):
        print(f"🔨 {t('Forge (Forgejo/Gitea): profiles, token, repos')}")
        choices = [
            {"section": t("Profiles & token")},
            {"prompt_description": t("Forge - List the profiles")},
            {"prompt_description": t("Forge - Add or edit a profile")},
            {"prompt_description": t("Forge - Store the API token")},
            {"prompt_description": t("Forge - Delete a profile")},
            {"section": t("The forge itself")},
            {"prompt_description": t("Forge - Check the connection")},
            {"prompt_description": t("Forge - List the repositories")},
            {
                "prompt_description": t(
                    "Forge - Create the repositories the manifest declares"
                )
            },
            {
                "prompt_description": t(
                    "Forge - Mirror the manifest from its upstreams"
                )
            },
            {"section": t("Outbound mirrors")},
            {
                "prompt_description": t(
                    "Forge - Declare which way a repository mirrors"
                )
            },
            {
                "prompt_description": t(
                    "Forge - Lay the outbound mirror on the forge"
                )
            },
            {
                "prompt_description": t(
                    "Forge - Show a repository's outbound mirrors"
                )
            },
        ]
        help_info = self.fill_help_info(choices)

        while True:
            status = click.prompt(help_info)
            print()
            if status == "0":
                return False
            elif status == "1":
                self._forge_list_profiles()
            elif status == "2":
                self._forge_edit_profile()
            elif status == "3":
                self._forge_store_token()
            elif status == "4":
                self._forge_delete_profile()
            elif status == "5":
                self._forge_check()
            elif status == "6":
                self._forge_list_repos()
            elif status == "7":
                self._forge_create_missing()
            elif status == "8":
                self._forge_mirror_manifest()
            elif status == "9":
                self._forge_mirror_direction()
            elif status == "10":
                self._forge_push_mirror_add()
            elif status == "11":
                self._forge_push_mirror_list()
            else:
                print(t("Command not found !"))

    # ------------------------------------------------------------------
    # Le coffre
    # ------------------------------------------------------------------
    def _forge_store(self):
        """Le magasin de secrets du dépôt, sans le trousseau système.

        « use_keyring=False » : un jeton de forge est un secret d'ÉQUIPE,
        rangé dans le coffre du dépôt que les postes partagent. Le trousseau
        du système ne suit ni la machine ni la personne suivante.
        """
        return SecretStore(kdbx_manager=self.kdbx_manager, use_keyring=False)

    def _forge_token(self, name, quiet=False):
        """Le jeton du profil, "" s'il n'y en a pas ou si le coffre refuse.

        Une chaîne vide plutôt qu'une exception : « pas encore de jeton » est
        un état NORMAL, que le menu affiche au lieu de le traiter comme une
        panne. Le client, lui, en fera le verdict NO_TOKEN.
        """
        try:
            return self._forge_store().get(profiles.secret_ref(name)) or ""
        except SecretError as refus:
            if not quiet:
                print(f"! {refus}")
            return ""

    def _forge_client(self, name):
        """(profil, client) pour `name`, ou (None, None) si le profil
        n'existe pas — le dire ici évite de le redire trois fois plus bas."""
        profile = profiles.load(name)
        if profile is None:
            print(f"! {t('Unknown profile:')} {name}")
            return None, None
        return profile, ForgeClient(profile, self._forge_token(name))

    # ------------------------------------------------------------------
    # Choisir
    # ------------------------------------------------------------------
    def _forge_select_profile(self):
        """Le nom d'un profil, "" si l'utilisateur renonce ou s'il n'y en a
        aucun. Un seul profil est pris sans question."""
        noms = profiles.names()
        if not noms:
            print(t("No forge profile yet: create one first."))
            return ""
        if len(noms) == 1:
            return noms[0]
        for rang, nom in enumerate(noms, start=1):
            print(f"  [{rang}] {nom}")
        reponse = input(f"{t('Profile number (empty to cancel): ')}").strip()
        if not reponse.isdigit() or not 1 <= int(reponse) <= len(noms):
            return ""
        return noms[int(reponse) - 1]

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------
    def _forge_list_profiles(self):
        tous = profiles.load_all()
        if not tous:
            print(t("No forge profile yet: create one first."))
            return
        for profile in tous:
            complet = profiles.with_defaults(profile)
            nom = complet.get("name", "")
            print(
                "  "
                + profile_line(
                    complet, bool(self._forge_token(nom, quiet=True))
                )
            )

    def _forge_edit_profile(self):
        """Crée ou modifie un profil. N'écrit RIEN si la saisie est refusée.

        Un profil à moitié valide sur le disque se relit sans se plaindre, et
        la panne se découvre au premier appel, loin d'ici.
        """
        nom = input(f"{t('Profile name: ')}").strip()
        if not nom:
            return
        actuel = profiles.load(nom) or dict(profiles.DEFAULTS, name=nom)
        propose = {
            "name": nom,
            "url": self._forge_ask(t("Forge URL: "), actuel.get("url", "")),
            "owner": self._forge_ask(
                t("Owning account or organisation: "), actuel.get("owner", "")
            ),
            "verify_tls": self._forge_ask_flag(
                t("Verify the TLS certificate"),
                bool(actuel.get("verify_tls", True)),
            ),
            "allow_plaintext": self._forge_ask_flag(
                t("Allow http to a remote address"),
                bool(actuel.get("allow_plaintext", False)),
            ),
            "role": self._forge_ask_role(
                str(actuel.get("role") or "").strip()
            ),
            "driver": actuel.get("driver", profiles.DEFAULTS["driver"]),
        }
        conflit = self._forge_autre_autorite(nom, propose["role"])
        if conflit:
            print(
                f"! {t('Another profile is already the authority:')}"
                f" {conflit}"
            )
            return
        try:
            propre = profiles.save(propose)
        except ValidationError as refus:
            print(f"! {refus}")
            return
        print(f"✓ {t('Profile saved:')} {propre['name']} — {propre['url']}")
        if not propre["verify_tls"]:
            print(f"  ⚠ {t('TLS verification is OFF for this profile.')}")

    def _forge_ask(self, question, defaut):
        """Une réponse vide GARDE la valeur en place.

        Retaper une adresse pour changer un drapeau la ferait fauter un jour
        sur deux, et une adresse fautive ne se voit qu'au premier appel.
        """
        reponse = input(f"{question}[{defaut}] ").strip()
        return reponse or defaut

    def _forge_ask_flag(self, question, defaut):
        marque = "O/n" if defaut else "o/N"
        reponse = input(f"{question} [{marque}] ").strip().lower()
        if not reponse:
            return defaut
        return reponse in ("o", "oui", "y", "yes", "1", "true")

    def _forge_ask_role(self, defaut):
        """Le rôle du profil, choisi par NUMÉRO parmi ceux que le code connaît.

        Rend un membre de `profiles.ROLES`, toujours. Vide garde celui en
        place, comme le reste du formulaire — et c'est ce qui manquait : le
        rôle n'étant pas demandé, le profil réécrit repartait au défaut, donc
        rouvrir l'autorité pour corriger un drapeau la RÉTROGRADAIT, sous un
        « ✓ enregistré » qui annonçait un succès.

        Une réponse qui ne désigne rien est dite et redemandée : retomber sur
        le rôle en place ferait croire au choix qu'on venait de rater.
        """
        roles = list(profiles.ROLES)
        courant = defaut if defaut in roles else ""
        print(f"\n  {t('Role of this profile')} :")
        for rang, role in enumerate(roles, start=1):
            marque = " ←" if role == courant else ""
            print(f"  [{rang}] {t(ROLES_DITS[role]['phrase'])}{marque}")
        while True:
            reponse = input(f"  [1-{len(roles)}] ").strip()
            if not reponse:
                return courant
            if reponse.isdigit() and 1 <= int(reponse) <= len(roles):
                return roles[int(reponse) - 1]
            print(f"  ! {t('Command not found !')}")

    @staticmethod
    def _forge_autre_autorite(nom, role):
        """Le ou les AUTRES profils qui se disent déjà l'autorité, ou "".

        Dit au geste, et non au premier appel qui en dépend. `canonical()`
        refuse deux autorités : poser la seconde n'en ajoute pas une, elle
        les annule toutes les deux, et l'écran d'avancement retombe à « à
        régler » sans que rien n'ait nommé le conflit.

        On REFUSE plutôt que de rétrograder l'autre en silence : laquelle des
        deux doit céder n'est pas une question que cet écran peut trancher.

        Lit `load_all` et non `canonical()`, qui lève quand deux existent
        déjà : un fichier écrit à la main ne doit pas rendre l'écran de
        correction inutilisable.
        """
        if role != profiles.ROLE_CANONIQUE:
            return ""
        autres = [
            p.get("name", "")
            for p in profiles.load_all()
            if p.get("name") != nom
            and str(p.get("role") or "").strip() == profiles.ROLE_CANONIQUE
        ]
        return ", ".join(sorted(autres))

    def _forge_delete_profile(self):
        nom = self._forge_select_profile()
        if not nom:
            return
        if not self._is_yes(input(f"{t('Delete')} « {nom} » ? [o/N] : ")):
            return
        if profiles.delete(nom):
            print(f"✓ {t('Profile deleted:')} {nom}")
        else:
            # Un profil venu de `todo.json` est partagé par l'équipe : le
            # menu n'écrit que dans le fichier privé, et faire semblant de
            # l'avoir supprimé le ferait réapparaître au prochain démarrage.
            print(f"! {t('Not in the private file, nothing deleted:')} {nom}")

    def _forge_store_token(self):
        """Dépose le jeton dans le coffre. Il ne s'affiche à aucun moment.

        `getpass` et non `input` : la saisie ne s'écrit pas à l'écran, donc
        ni dans un partage d'écran, ni dans le tampon du terminal.
        """
        nom = self._forge_select_profile()
        if not nom:
            return
        jeton = getpass.getpass(t("API token (not echoed): "))
        if not jeton:
            print(t("Empty: nothing stored."))
            return
        try:
            self._forge_store().set(profiles.secret_ref(nom), jeton)
        except SecretError as refus:
            print(f"! {refus}")
            return
        print(f"✓ {t('Token stored for')} {nom}")

    def _forge_check(self):
        """Le premier geste après avoir déposé un jeton.

        Il coûte un aller-retour et distingue les quatre pannes qui se
        ressemblent, AVANT qu'une opération d'écriture échoue à moitié.
        """
        nom = self._forge_select_profile()
        if not nom:
            return
        profile, client = self._forge_client(nom)
        if client is None:
            return
        reponse = client.whoami()
        print(f"  {verdict_sentence(reponse.kind)}")
        if reponse.detail:
            print(f"  {t('The forge said:')} {reponse.detail}")
        if reponse.kind == api.OK and isinstance(reponse.data, dict):
            print(f"  {t('Connected as:')} {reponse.data.get('login', '?')}")

    def _forge_list_repos(self):
        nom = self._forge_select_profile()
        if not nom:
            return
        _profile, client = self._forge_client(nom)
        if client is None:
            return
        reponse = client.repos()
        if reponse.kind != api.OK:
            print(f"  {verdict_sentence(reponse.kind)}")
            if reponse.detail:
                print(f"  {t('The forge said:')} {reponse.detail}")
            return
        depots = reponse.data or []
        for depot in depots:
            visibilite = t("private") if depot.get("private") else t("PUBLIC")
            print(
                f"  {depot.get('full_name', depot.get('name', '?'))}"
                f" [{visibilite}]"
            )
        print(f"  {len(depots)} {t('repositories')}")

    # ------------------------------------------------------------------
    # Le miroir du manifeste
    # ------------------------------------------------------------------
    def _forge_manifest_path(self):
        """Le manifeste à miroiter, "" si l'utilisateur renonce.

        Celui du CHECKOUT d'abord — c'est ce que le poste utilise vraiment,
        et trois autres scripts du dépôt y défaultent déjà. Absent, on
        DEMANDE plutôt que de lire un autre fichier en silence : miroiter un
        manifeste qui n'est pas celui en service crée les mauvais dépôts, et
        rien ne le dit.
        """
        if os.path.exists(MANIFEST_DEFAULT):
            return MANIFEST_DEFAULT
        print(f"! {t('No synced manifest at')} {MANIFEST_DEFAULT}")
        print(f"  {t('Run repo sync, or give a manifest path below.')}")
        for candidat in sorted(glob.glob("manifest/*.xml"))[:10]:
            print(f"    {candidat}")
        reponse = input(f"{t('Manifest path (empty to cancel): ')}").strip()
        if not reponse:
            return ""
        if not os.path.exists(reponse):
            print(f"! {t('No such file:')} {reponse}")
            return ""
        return reponse

    def _forge_declared_projects(self, chemin):
        """Les projets du manifeste, [] s'il est illisible.

        L'analyse elle-même vit dans `script.forge.mirror`, qui prend du
        TEXTE : elle y est pure, donc vérifiable sur les neuf cents projets
        du dépôt. Ce qui reste ici est la lecture du fichier et la phrase.

        Un XML tronqué est un ÉTAT et non une panne du menu : un `repo sync`
        interrompu en laisse un, et remonter une trace d'analyse XML ne dit
        pas quoi faire.
        """
        try:
            with open(chemin, encoding="utf-8") as fichier:
                texte = fichier.read()
            return mirror.parse_projects(texte)
        except (OSError, UnicodeDecodeError, ElementTree.ParseError) as refus:
            print(f"! {t('Unreadable manifest:')} {refus}")
            return []

    def _forge_create_missing(self):
        """Crée sur la forge les dépôts que le manifeste déclare.

        LE PLAN D'ABORD, l'exécution ensuite : la liste fait deux cents
        entrées, et une forge à nettoyer coûte plus cher que la relire.

        UNE PANNE N'ARRÊTE PAS LES AUTRES. Un dépôt déjà présent sous un nom
        que le rapprochement n'a pas vu répond 409 ; abandonner là laisserait
        les cent quatre-vingt-dix-neuf suivants non créés, et rejouer
        buterait sur le même.
        """
        nom = self._forge_select_profile()
        if not nom:
            return
        chemin = self._forge_manifest_path()
        if not chemin:
            return
        projets = self._forge_declared_projects(chemin)
        if not projets:
            print(t("The manifest declares no project."))
            return
        declares = [projet["name"] for projet in projets]
        _profile, client = self._forge_client(nom)
        if client is None:
            return

        reponse = client.repos()
        if reponse.kind != api.OK:
            print(f"  {verdict_sentence(reponse.kind)}")
            if reponse.detail:
                print(f"  {t('The forge said:')} {reponse.detail}")
            return
        presents = [
            depot.get("full_name") or depot.get("name") or ""
            for depot in (reponse.data or [])
        ]

        projet = mirror.plan(declares, presents)
        print(
            f"  {len(projet.already)} {t('already there,')}"
            f" {len(projet.to_create)} {t('to create.')}"
        )
        for collision, noms in projet.collisions.items():
            # Une collision reste vraie même quand le dépôt est là : un seul
            # des projets est miroité, et le miroir est incomplet.
            print(
                f"  ⚠ {t('Same forge name for:')} {', '.join(noms)}"
                f" → « {collision} »"
            )
        if not projet.to_create:
            return
        for a_creer in projet.to_create:
            print(f"    + {a_creer}")
        if not self._is_yes(
            input(f"\n{t('Create these repositories? (o/N): ')}")
        ):
            return

        faits, refuses = 0, []
        for a_creer in projet.to_create:
            resultat = client.create_repo(a_creer)
            if resultat.kind == api.OK:
                faits += 1
            else:
                refuses.append((a_creer, resultat.kind, resultat.detail))
        print(f"  ✓ {faits} {t('created.')}")
        for a_creer, verdict, detail in refuses:
            print(f"  ✗ {a_creer} : {verdict_sentence(verdict)}")
            if detail:
                print(f"      {detail}")

    # ------------------------------------------------------------------
    # Le miroir SORTANT : ce qui vit ici et part se montrer
    # ------------------------------------------------------------------
    def _forge_mirror_sens(self, profil, projets, nom_forge):
        """Le sens DÉRIVÉ pour ce dépôt, et la surcharge qui le corrige.

        Rend (dérivé, surcharge, effectif). Les trois, parce que l'écran
        doit pouvoir dire « le manifeste dit entrant, ce site déclare
        sortant » : ne montrer que l'effectif ferait croire à une dérivation
        qui se trompe, là où c'est un réglage qui la corrige.
        """
        amonts = mirror.amonts_du_manifeste(projets, profil.get("url", ""))
        adresse = ""
        for projet in projets:
            if mirror.forge_name(projet.get("name", "")) == nom_forge:
                adresse = projet.get("clone_url", "")
                break
        derive = mirror.sens(adresse, amonts)
        surcharge = mirror.surcharges().get(nom_forge, "")
        return derive, surcharge, (surcharge or derive)

    def _forge_pick_repo(self, projets):
        """Un nom de dépôt DE FORGE, choisi par numéro, ou "".

        Les noms viennent du manifeste et non d'une saisie : c'est lui qui
        sait comment la forge les nomme, et un nom retapé se trompe d'un
        caractère sans que rien ne le dise avant l'appel.
        """
        noms = sorted(
            {
                mirror.forge_name(p.get("name", ""))
                for p in projets
                if mirror.forge_name(p.get("name", ""))
            }
        )
        if not noms:
            print(t("The manifest declares no project."))
            return ""
        for rang, nom in enumerate(noms, start=1):
            print(f"  [{rang}] {nom}")
        reponse = input(t("Repository number (empty to cancel): ")).strip()
        if not reponse.isdigit() or not 1 <= int(reponse) <= len(noms):
            return ""
        return noms[int(reponse) - 1]

    def _forge_mirror_direction(self):
        """Déclare le sens du miroir d'un dépôt, ou retire la déclaration.

        LE SENS SE DÉRIVE, ET LA DÉCLARATION LE CORRIGE. Un dépôt dont
        l'adresse de clone est chez un amont y vit : la forge le SUIT. La
        surcharge existe pour ce que la dérivation ne sait pas dire —
        pousser vers un amont un dépôt qui en vient aussi — et l'écran
        montre donc les DEUX, faute de quoi on croirait la dérivation
        fautive là où c'est un réglage qui la corrige.
        """
        nom = self._forge_select_profile()
        if not nom:
            return
        profil = profiles.load(nom)
        if profil is None:
            print(f"! {t('Unknown profile:')} {nom}")
            return
        chemin = self._forge_manifest_path()
        if not chemin:
            return
        projets = self._forge_declared_projects(chemin)
        if not projets:
            print(t("The manifest declares no project."))
            return
        depot = self._forge_pick_repo(projets)
        if not depot:
            return
        derive, surcharge, effectif = self._forge_mirror_sens(
            profil, projets, depot
        )
        print(f"\n  {t('The manifest derives:')} {t(SENS_DITS[derive])}")
        if surcharge:
            print(f"  {t('This site declares:')} {t(SENS_DITS[surcharge])}")
        else:
            print(f"  {t('This site declares nothing.')}")
        choix = list(mirror.SENS)
        for rang, sens in enumerate(choix, start=1):
            marque = " ←" if sens == effectif else ""
            print(f"  [{rang}] {t(SENS_DITS[sens])}{marque}")
        print(f"  [0] {t('follow the manifest (remove the declaration)')}")
        reponse = input(f"  [0-{len(choix)}] ").strip()
        if not reponse.isdigit() or int(reponse) > len(choix):
            print(t("Command not found !"))
            return
        voulu = "" if reponse == "0" else choix[int(reponse) - 1]
        try:
            mirror.declarer(depot, voulu)
        except ValidationError as refus:
            print(f"! {refus}")
            return
        if voulu:
            print(f"✓ {depot} : {t(SENS_DITS[voulu])}")
        else:
            print(f"✓ {depot} : {t('follows the manifest again')}")

    def _forge_push_mirror_add(self):
        """Pose sur la forge le miroir sortant d'un dépôt déclaré tel.

        DÉCLARÉ D'ABORD, POSÉ ENSUITE. Poser un miroir sur un dépôt que le
        site n'a pas déclaré sortant ferait pousser vers un amont ce que la
        dérivation dit entrant, c'est-à-dire écraser chez le tiers ce qu'on
        en avait reçu.

        LE JETON DU MIROIR N'EST PAS CELUI DE LA FORGE. Le premier ouvre
        l'amont vers lequel elle pousse, le second ouvre la forge ; les
        confondre donnerait à la forge un jeton qui écrit chez le tiers, ou
        l'inverse. Il ne s'affiche à aucun moment, et la forge ne le rend
        jamais une fois posé.
        """
        nom = self._forge_select_profile()
        if not nom:
            return
        profil, client = self._forge_client(nom)
        if client is None:
            return
        chemin = self._forge_manifest_path()
        if not chemin:
            return
        projets = self._forge_declared_projects(chemin)
        if not projets:
            print(t("The manifest declares no project."))
            return
        depot = self._forge_pick_repo(projets)
        if not depot:
            return
        _derive, _surcharge, effectif = self._forge_mirror_sens(
            profil, projets, depot
        )
        if effectif != mirror.SORTANT:
            print(f"! {depot} : {t('not declared outbound; nothing laid.')}")
            print(f"  {t('Declare it first with the entry above.')}")
            return
        proprio = profil.get("owner", "")
        # LIRE AVANT DE POSER : la forge accepte deux miroirs vers la même
        # adresse, et l'on obtient alors deux poussées qui se courent après.
        # Le refus qui le dirait n'existe pas.
        deja = client.push_mirrors(proprio, depot)
        if deja.kind != api.OK:
            print(f"  {verdict_sentence(deja.kind)}")
            if deja.detail:
                print(f"  {t('The forge said:')} {deja.detail}")
            return
        adresse = self._forge_ask(t("Upstream address to push to: "), "")
        if not adresse:
            print(t("Empty: nothing laid."))
            return
        presents = [(m.get("remote_address") or "") for m in (deja.data or [])]
        if adresse in presents:
            print(f"! {depot} : {t('a mirror already pushes there.')}")
            return
        compte = self._forge_ask(t("Account on the upstream: "), "")
        jeton = getpass.getpass(t("Upstream token (not echoed): "))
        if not jeton:
            print(t("Empty: nothing laid."))
            return
        # DÉPOSÉ AU COFFRE AUSSI. La forge ne rend jamais ce jeton : sans
        # copie ici, en changer obligerait à le retrouver ailleurs, et le
        # retirer puis le reposer est le seul moyen d'en changer.
        try:
            self._forge_store().set(profiles.mirror_secret_ref(nom), jeton)
        except SecretError as refus:
            print(f"! {refus}")
        rendu = client.add_push_mirror(proprio, depot, adresse, compte, jeton)
        if rendu.kind != api.OK:
            print(f"  ✗ {verdict_sentence(rendu.kind)}")
            if rendu.detail:
                print(f"  {t('The forge said:')} {rendu.detail}")
            return
        print(f"✓ {depot} → {adresse}")

    def _forge_push_mirror_list(self):
        """Ce que la forge pousse DÉJÀ pour un dépôt.

        À lire avant d'en poser un, et après : c'est le seul endroit qui
        dise si la forge pousse vraiment, là où la configuration locale ne
        dit que ce qu'on a voulu.
        """
        nom = self._forge_select_profile()
        if not nom:
            return
        profil, client = self._forge_client(nom)
        if client is None:
            return
        chemin = self._forge_manifest_path()
        if not chemin:
            return
        projets = self._forge_declared_projects(chemin)
        depot = self._forge_pick_repo(projets) if projets else ""
        if not depot:
            return
        rendu = client.push_mirrors(profil.get("owner", ""), depot)
        if rendu.kind != api.OK:
            print(f"  {verdict_sentence(rendu.kind)}")
            if rendu.detail:
                print(f"  {t('The forge said:')} {rendu.detail}")
            return
        miroirs = rendu.data or []
        if not miroirs:
            # LE DIRE. Une liste vide imprimée comme rien se confond avec un
            # appel qui n'a pas eu lieu.
            print(f"  {t('The forge pushes this repository nowhere.')}")
            return
        for miroir in miroirs:
            # Le JETON ne figure dans aucune de ces lignes : la forge ne le
            # rend pas, et le redemander pour l'afficher serait le sortir du
            # coffre pour rien.
            print(
                f"  {miroir.get('remote_address', '?')}"
                f"  [{miroir.get('interval', '?')}]"
                f"  {miroir.get('last_update') or t('never pushed')}"
            )

    def _forge_mirror_manifest(self):
        """Miroite sur la forge les dépôts du manifeste, depuis leur amont.

        UN MIROIR PLUTÔT QU'UN DÉPÔT VIDE. « Créer » donne des dépôts sans
        contenu, qu'il faut ensuite pousser depuis un poste ; miroiter fait
        tirer la forge elle-même, et elle continue de le faire.

        L'AMONT VIENT DU MANIFESTE, pas d'une saisie : c'est lui qui sait
        quel « remote » sert quel projet, héritage du remote par défaut
        compris. Une adresse VIDE est écartée et nommée — miroiter sur rien
        ferait répondre la forge sans dire qu'il manque un remote.
        """
        nom = self._forge_select_profile()
        if not nom:
            return
        chemin = self._forge_manifest_path()
        if not chemin:
            return
        projets = self._forge_declared_projects(chemin)
        if not projets:
            print(t("The manifest declares no project."))
            return
        _profile, client = self._forge_client(nom)
        if client is None:
            return

        reponse = client.repos()
        if reponse.kind != api.OK:
            print(f"  {verdict_sentence(reponse.kind)}")
            if reponse.detail:
                print(f"  {t('The forge said:')} {reponse.detail}")
            return
        presents = [
            depot.get("full_name") or depot.get("name") or ""
            for depot in (reponse.data or [])
        ]

        sans_amont = [p["name"] for p in projets if not p["clone_url"]]
        for orphelin in sans_amont:
            print(f"  ⚠ {t('No upstream for:')} {orphelin}")
        amont = {
            mirror.forge_name(p["name"]): p["clone_url"]
            for p in projets
            if p["clone_url"]
        }

        projet = mirror.plan(list(amont), presents)
        print(
            f"  {len(projet.already)} {t('already there,')}"
            f" {len(projet.to_create)} {t('to mirror.')}"
        )
        for collision, noms in projet.collisions.items():
            print(
                f"  ⚠ {t('Same forge name for:')} {', '.join(noms)}"
                f" → « {collision} »"
            )
        if not projet.to_create:
            return
        for a_miroiter in projet.to_create:
            print(f"    ↓ {a_miroiter}  ←  {amont[a_miroiter]}")
        if not self._is_yes(
            input(f"\n{t('Mirror these repositories? (o/N): ')}")
        ):
            return

        faits, refuses = 0, []
        for a_miroiter in projet.to_create:
            resultat = client.migrate(amont[a_miroiter], a_miroiter)
            if resultat.kind == api.OK:
                faits += 1
            else:
                refuses.append((a_miroiter, resultat.kind, resultat.detail))
        print(f"  ✓ {faits} {t('mirrored.')}")
        for a_miroiter, verdict, detail in refuses:
            print(f"  ✗ {a_miroiter} : {verdict_sentence(verdict)}")
            if detail:
                print(f"      {detail}")
