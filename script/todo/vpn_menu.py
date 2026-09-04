#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Le menu VPN : profils, secrets, montée, diagnostic.

La frontière avec `script/vpn/` est nette : ici on DEMANDE (quel profil,
quelle adresse, quel PSK) et on affiche ; là-bas on décide et on exécute. Ce
fichier ne connaît ni ipsec.conf, ni xl2tpd, ni aucun chemin système.

Deux chemins d'exécution, pour une raison :

· les profils et les secrets sont manipulés EN PROCESSUS, par les modules
  `script.vpn.profiles` et `script.vpn.vault` — le mot de passe maître du
  coffre est déjà en mémoire ici, le redemander à un sous-processus serait
  une saisie de plus à chaque geste ;
· le montage, la descente et le diagnostic passent par `script/vpn/vpn.py`
  en sous-processus — ils durent, ils parlent, et ils appellent sudo. La
  sortie en direct est ce qui rend un « ipsec up » suivable.
"""

import getpass
import os

import click

from script.todo.todo_i18n import t
from script.vpn import anyconnect_xml, presets, profiles
from script.vpn.drivers import DRIVERS, get_driver
from script.vpn.vault import VaultError, VpnVault, secrets_to_env

# `-u` : sans lui, la sortie du script est mise en tampon par blocs dès
# qu'elle est redirigée, et une montée de tunnel de trente secondes
# n'afficherait rien avant la fin.
VPN_CLI = "./.venv.erplibre/bin/python -u ./script/vpn/vpn.py"

# Nommé pour que la clé i18n tienne sur une ligne lisible — c'est la même
# chaîne que celle du CLI, et elle est longue parce qu'elle doit dire quoi
# faire, pas seulement que quelque chose ne va pas.
# Ce qu'on dit à qui n'a reçu du site qu'une passerelle et des
# identifiants : le profil est utilisable, et le premier montage dira
# lui-même quel réseau ajouter.
NO_ROUTE_NOTE = (
    "No network routed yet: this tunnel will only reach the remote host."
    " Connect once — the address you get tells you which network to add."
)

# La légende de l'étoile posée sur les technologies non éprouvées. Elle dit
# ce qui manque — la confrontation au terrain — et non que le code serait
# douteux : les tests unitaires, eux, sont là.
UNPROVEN_NOTE = "never mounted against a real server: only unit tests cover it"

# Où poser un préréglage quand il n'y en a aucun. Dit les DEUX répertoires,
# parce qu'ils ne servent pas au même usage : l'un est suivi par git et ne
# doit rien porter d'identifiant, l'autre est ignoré et existe pour ça.
PRESET_LOCATION_NOTE = (
    "Drop a .json file in conf/vpn_presets/ (shared, nothing identifying)"
    " or in private/vpn/presets/ (git-ignored, where a site preset goes)."
)

# Ce qu'on dit quand le nom tapé désigne un profil déjà là. Dit LEQUEL des
# deux gagne, champ par champ : sans cela, on ne sait pas si rejouer un
# préréglage remet la passerelle à jour ou efface les routes ajoutées.
PRESET_REPLAYED_NOTE = (
    "This profile already exists: the preset refreshes what it declares,"
    " everything personal is kept."
)

# Où le client de Cisco dépose les profils qu'un site distribue. Le dire
# évite d'avoir à le chercher, et c'est le seul endroit où il se trouve
# quand le client graphique a déjà servi sur la machine.
ANYCONNECT_LOCATION_NOTE = (
    "An AnyConnect profile usually sits in"
    " /opt/cisco/secureclient/vpn/profile/ (or .../anyconnect/profile/)."
)

# Ce que le fichier ne dit PAS, et qu'il reste donc à régler. Le profil
# AnyConnect ne déclare pas la méthode d'authentification : c'est le
# concentrateur qui l'annonce à la connexion.
ANYCONNECT_NEXT_STEP = (
    "Next step: create a profile from one of them. The .xml carries no"
    " username and does not say whether the service authenticates by"
    " password or by web form."
)

MASTER_PASSWORD_WARNING = (
    "The vault MASTER password is stored in the configuration in clear"
    " text. Remove it and type it on demand."
)


# Les technologies se choisissent par LETTRE. Le menu qui précède numérote
# ses entrées ; une seconde liste numérotée juste après invite à retaper un
# numéro de menu — et c'est exactement ce qui s'est produit. La lettre dit
# « autre question ».
DRIVER_LETTERS = "abcdefghijklmnopqrstuvwxyz"


def match_driver(answer, names):
    """Le pilote désigné par `answer`.

    Rend le nom du pilote, "" si rien ne correspond, ou la LISTE des
    candidats quand c'est ambigu — le dire vaut mieux qu'en choisir un.

    Trois formes, dans cet ordre : la lettre affichée ; le rang, parce que
    quelqu'un tapera un chiffre et qu'il a raison de le faire vu le menu qui
    précède ; et un début de libellé, parce que devant « L2TP/IPsec PSK » on
    tape « L ». « open » désigne deux pilotes : celui-là est refusé en le
    nommant.
    """
    answer = (answer or "").strip().lower()
    if not answer:
        return ""
    if len(answer) == 1 and answer in DRIVER_LETTERS:
        index = DRIVER_LETTERS.index(answer)
        if index < len(names):
            return names[index]
    if answer.isdigit():
        index = int(answer) - 1
        return names[index] if 0 <= index < len(names) else ""
    matches = [
        name
        for name in names
        if DRIVERS[name].label.lower().startswith(answer)
        or name.startswith(answer)
    ]
    if len(matches) == 1:
        return matches[0]
    return matches or ""


class VpnMenuMixin:
    # ------------------------------------------------------------------
    # Menu
    # ------------------------------------------------------------------
    def prompt_execute_vpn(self):
        print(f"🔐 {t('VPN tunnels: connect, profiles, vault secrets')}")
        choices = [
            {"section": t("Connection")},
            {"prompt_description": t("VPN - Connect a profile")},
            {"prompt_description": t("VPN - Disconnect a profile")},
            {"prompt_description": t("VPN - Status and diagnosis")},
            {"section": t("Profiles & secrets")},
            {
                "prompt_description": t(
                    "VPN - Create a profile from a site preset"
                )
            },
            {
                "prompt_description": t(
                    "VPN - Import an AnyConnect profile (.xml)"
                )
            },
            {"prompt_description": t("VPN - Add or edit a profile")},
            {"prompt_description": t("VPN - Store secrets in the vault")},
            {
                "prompt_description": t(
                    "VPN - Show the rendered configuration (dry-run)"
                )
            },
            {"prompt_description": t("VPN - Delete a profile")},
            {"section": t("Host")},
            {"prompt_description": t("VPN - Install the client packages")},
            {"prompt_description": t("VPN - What can this machine do?")},
        ]
        help_info = self.fill_help_info(choices)

        while True:
            status = click.prompt(help_info)
            print()
            if status == "0":
                return False
            elif status == "1":
                self._vpn_connect()
            elif status == "2":
                self._vpn_disconnect()
            elif status == "3":
                self._vpn_diagnose()
            elif status == "4":
                self._vpn_from_preset()
            elif status == "5":
                self._vpn_import_anyconnect()
            elif status == "6":
                self._vpn_edit_profile()
            elif status == "7":
                self._vpn_store_secrets()
            elif status == "8":
                self._vpn_show_config()
            elif status == "9":
                self._vpn_delete_profile()
            elif status == "10":
                self._vpn_install()
            elif status == "11":
                self._vpn_check()
            else:
                print(t("Command not found !"))

    # ------------------------------------------------------------------
    # Actions déléguées au CLI
    # ------------------------------------------------------------------
    def _vpn_cli(self, arguments, secrets_env=None):
        self.execute.exec_command_live(
            f"{VPN_CLI} {arguments}",
            source_erplibre=False,
            new_env=secrets_env or None,
        )

    def _vpn_secrets_env(self, name):
        """Secrets du profil, prêts pour l'environnement du sous-processus.

        Le coffre est déjà ouvert ici : le faire rouvrir par `vpn.py` ferait
        retaper le mot de passe maître deux fois par connexion, puisqu'un
        essai à blanc précède le montage. Rend {} quand le coffre n'est pas
        joignable — `vpn.py` demandera alors lui-même, et le dira.
        """
        profile = profiles.load(name)
        driver_cls = get_driver(profile["driver"]) if profile else None
        if driver_cls is None or not driver_cls.secret_fields:
            return {}
        fields = tuple(key for key, _, _ in driver_cls.secret_fields)
        vault = VpnVault(self.config_file, self.kdbx_manager)
        if not vault.vault_path():
            return {}
        try:
            values = vault.read(profiles.secret_title(name), fields=fields)
        except VaultError as error:
            print(f"! {error}")
            return {}
        return secrets_to_env({key: values.get(key, "") for key in fields})

    def _vpn_connect(self):
        name = self._vpn_select_profile()
        if not name:
            return
        # Lu UNE fois pour les deux exécutions qui suivent.
        secrets_env = self._vpn_secrets_env(name)
        # Le plan d'abord, l'exécution ensuite : monter un tunnel réécrit
        # /etc/ipsec.conf et la table de routage. Le voir avant coûte une
        # touche et évite de découvrir une faute de frappe dans un journal.
        self._vpn_cli(f"up --profile {name} --dry-run", secrets_env)
        if not self._is_yes(input(f"\n{t('Run this plan? (y/N): ')}")):
            return
        self._vpn_cli(f"up --profile {name}", secrets_env)

    def _vpn_disconnect(self):
        name = self._vpn_select_profile()
        if name:
            self._vpn_cli(f"down --profile {name}")

    def _vpn_diagnose(self):
        name = self._vpn_select_profile()
        if name:
            self._vpn_cli(f"diagnose --profile {name}")

    def _vpn_show_config(self):
        name = self._vpn_select_profile()
        if name:
            self._vpn_cli(
                f"up --profile {name} --dry-run",
                self._vpn_secrets_env(name),
            )

    def _vpn_check(self):
        self._vpn_cli("check")

    def _vpn_install(self):
        driver_cls = self._vpn_pick_driver(None)
        if driver_cls is None:
            return
        print(f"\n{t('The installation requires sudo.')}")
        self._vpn_cli(f"install --driver {driver_cls.name}")

    # ------------------------------------------------------------------
    # Profils
    # ------------------------------------------------------------------
    def _vpn_select_profile(self):
        """Nom du profil choisi, "" si l'utilisateur renonce."""
        all_profiles = [profiles.with_defaults(p) for p in profiles.load_all()]
        if not all_profiles:
            print(t("No VPN profile yet: create one first."))
            return ""
        for index, profile in enumerate(all_profiles, start=1):
            target = (
                t("all traffic")
                if profile["default_route"]
                else ", ".join(profile["routes"])
            )
            print(
                f"[{index}] {profile['name']:<20}"
                f" {profile['server']:<26} {target}"
            )
        answer = input(f"{t('Profile number (0 to go back)')} : ").strip()
        if not answer.isdigit() or not 1 <= int(answer) <= len(all_profiles):
            if answer not in ("0", ""):
                print(t("Unknown choice."))
            return ""
        return all_profiles[int(answer) - 1]["name"]

    def _vpn_from_preset(self):
        """Crée un profil à partir d'un préréglage de site.

        Le préréglage porte ce que l'établissement publie et qui est le même
        pour tout le monde ; il ne reste à taper que l'identifiant. Le
        formulaire est celui de `_vpn_edit_profile`, amorcé : dupliquer les
        questions ici ferait vivre deux formulaires qui divergeraient au
        prochain champ ajouté à un pilote.
        """
        found, errors = presets.load_all()
        for error in errors:
            print(f"! {t('Unreadable preset: ')}{error}")
        if not found:
            print(t("No site preset available."))
            print(f"  {t(PRESET_LOCATION_NOTE)}")
            return
        for index, preset in enumerate(found, start=1):
            print(
                f"[{index}] {presets.label(preset):<34}"
                f" {preset.get('server', ''):<28}"
                f" {t(preset.get('hint', '') or '')}"
            )
        answer = input(f"{t('Preset number (0 to go back)')} : ").strip()
        if not answer.isdigit() or not 1 <= int(answer) <= len(found):
            if answer not in ("0", ""):
                print(t("Unknown choice."))
            return
        preset = found[int(answer) - 1]
        print(f"\n{t('An empty answer keeps the preset value.')}")
        name = input(
            f"{t('Profile name (lowercase, digits, - or _)')} : "
        ).strip()
        if not name:
            return
        existing = profiles.load(name)
        seed = presets.apply(preset, name)
        if existing:
            print(f"! {t(PRESET_REPLAYED_NOTE)}")
            # Le PRÉRÉGLAGE gagne sur les champs qu'il déclare : rejouer un
            # préréglage sur un profil existant sert à le remettre à jour
            # après un déménagement de passerelle ou un groupe renommé, et
            # garder l'ancienne valeur ne ferait rien de ce qu'on demande.
            #
            # Le reste vient du profil, parce que c'est ce qui est PERSONNEL
            # et qu'aucun préréglage ne porte : l'identifiant, les routes
            # ajoutées à la main, le certificat épinglé, l'adresse témoin.
            #
            # `k in seed` borne la reprise aux champs que le pilote du
            # préréglage connaît : sur un profil qui change de technologie,
            # recopier tout ferait suivre une clé WireGuard dans un profil
            # OpenConnect, où rien ne la lirait jamais.
            declared = set(preset) - set(presets.META_KEYS)
            seed.update(
                {
                    key: value
                    for key, value in existing.items()
                    if key in seed and key not in declared
                }
            )
        self._vpn_edit_profile(seed=seed)

    def _vpn_import_anyconnect(self):
        """Transforme un profil AnyConnect (`.xml`) en préréglages.

        Le fichier qu'un site distribue porte déjà le nom d'hôte et le
        groupe de connexion, et c'est ce dernier qui décide quel service du
        concentrateur on joint. Le retaper à la main est l'occasion de se
        tromper sur le seul champ qui compte.

        Écrit dans `private/vpn/presets/`, jamais dans `conf/` : le fichier
        nomme un établissement.
        """
        print(t(ANYCONNECT_LOCATION_NOTE))
        path = input(f"{t('Path to the .xml profile')} : ").strip()
        if not path:
            return
        try:
            found = anyconnect_xml.parse_file(os.path.expanduser(path))
        except anyconnect_xml.ProfileXmlError as error:
            print(f"\n✗ {error}")
            return

        print()
        for preset in found:
            print(f"  {presets.label(preset)}")
            print(f"    {t('Gateway')}          : {preset['server']}")
            print(
                f"    {t('Connection group')} :"
                f" {preset['oc_usergroup'] or t('none')}"
            )
        stem = os.path.splitext(os.path.basename(path))[0]
        stem = presets.slug_stem(stem)
        written = presets.save(found, stem)
        print(f"\n✓ {t('Presets written: ')}{written}")
        print(f"  {t(ANYCONNECT_NEXT_STEP)}")

    def _vpn_edit_profile(self, seed=None):
        """Crée ou modifie un profil, quelle que soit la technologie.

        Les questions viennent du PILOTE (`form_fields`) : ce menu ne sait
        pas qu'un profil L2TP a un utilisateur PPP ni qu'un profil WireGuard
        a une clé de pair. Ajouter une technologie n'ajoute donc pas une
        ligne ici.

        Une réponse vide garde la valeur actuelle : modifier une seule route
        ne doit pas obliger à ressaisir tout le reste.

        `seed` amorce le formulaire avec un profil déjà rempli — un
        préréglage de site. Il porte alors le nom ET la technologie, donc les
        deux questions correspondantes ne sont pas posées : le préréglage y a
        déjà répondu, et redemander « quelle technologie ? » invite à
        contredire le seul champ qu'on ne doit pas changer.
        """
        if seed is not None:
            current = dict(seed)
            name = current["name"]
            driver_cls = get_driver(current.get("driver"))
            if driver_cls is None:
                print(f"✗ {t('Unknown driver: ')}{current.get('driver')}")
                return
        else:
            name = input(
                f"{t('Profile name (lowercase, digits, - or _)')} : "
            ).strip()
            if not name:
                return
            current = profiles.load(name) or {"name": name}
            driver_cls = self._vpn_pick_driver(current.get("driver"))
            if driver_cls is None:
                return

        # Les défauts DU PILOTE CHOISI, pour que chaque question ait un
        # défaut sensé même sur un profil qui change de technologie.
        draft = profiles.with_defaults(dict(current, driver=driver_cls.name))

        draft["server"] = self._vpn_ask(
            t(driver_cls.server_label), draft.get("server", "")
        )
        # L'identité d'abord, le routage ensuite : c'est l'ordre du document
        # que le site remet — passerelle, utilisateur, mot de passe, clé —
        # et le routage est une question à part, à laquelle ce document ne
        # répond souvent pas.
        self._vpn_ask_fields(draft, driver_cls, advanced=False)
        draft["routes"] = self._vpn_ask(
            t("Networks to reach, comma-separated"),
            ", ".join(draft.get("routes", [])),
        )
        draft["default_route"] = self._vpn_ask_flag(
            t("Send ALL traffic through the tunnel?"),
            draft.get("default_route", False),
        )
        draft["probe"] = self._vpn_ask(
            t("Witness address reachable only through the tunnel (optional)"),
            draft.get("probe", ""),
        )
        if self._is_yes(input(f"{t('Advanced settings? (y/N)')} : ")):
            if driver_cls.uses_mtu:
                draft["mtu"] = self._vpn_ask(
                    t("MTU"), str(draft.get("mtu", 1280))
                )
            self._vpn_ask_fields(draft, driver_cls, advanced=True)

        try:
            saved = profiles.save(draft)
        except profiles.ProfileError as error:
            print(f"\n✗ {t('Profile refused: ')}{error}")
            return
        print(f"\n✓ {t('Profile saved: ')}{saved['name']}")
        if not saved["routes"] and not saved["default_route"]:
            print(f"  {t(NO_ROUTE_NOTE)}")
        if driver_cls.secret_fields:
            print(f"  {t('Next step: store its secrets in the vault.')}")
        else:
            print(
                f"  {t('No secret to store: this one authenticates over SSH.')}"
            )

    def _vpn_ask_fields(self, draft, driver_cls, advanced):
        """Déroule les champs déclarés par le pilote."""
        for key, label, kind, is_advanced in driver_cls.form_fields:
            if bool(is_advanced) != advanced:
                continue
            if kind == "flag":
                draft[key] = self._vpn_ask_flag(
                    t(label), draft.get(key, False)
                )
            else:
                draft[key] = self._vpn_ask(
                    t(label), str(draft.get(key, "") or "")
                )

    @staticmethod
    def _vpn_pick_driver(current):
        """La technologie, par lettre, avec un conseil par ligne.

        C'est la seule décision du formulaire où l'utilisateur a besoin
        d'aide : le reste se déduit de ce que le site lui a donné.

        Une étoile marque les technologies qu'aucun serveur réel n'a
        encore validées, et une légende dit ce qu'elle signifie : la liste
        montre autrement cinq choix d'apparence égale.

        `[0] Retour` est là comme dans tous les menus de ce CLI : sans lui,
        on est coincé dans le formulaire dès qu'on a tapé un nom de profil.
        """
        names = list(DRIVERS)
        if len(names) == 1:
            return DRIVERS[names[0]]
        default = current if current in DRIVERS else names[0]
        print(f"\n{t('Which technology?')}")
        unproven = False
        for letter, name in zip(DRIVER_LETTERS, names):
            driver_cls = DRIVERS[name]
            mark = " ←" if name == default else ""
            # L'étoile occupe une colonne à elle : sans cela, les lignes
            # marquées décaleraient leur conseil et la liste se lirait mal.
            star = " " if driver_cls.proven else "*"
            unproven = unproven or not driver_cls.proven
            print(
                f"[{letter}] {driver_cls.label:<16}{star}"
                f" {t(driver_cls.hint)}{mark}"
            )
        if unproven:
            print(f"    * {t(UNPROVEN_NOTE)}")
        print(f"[0] {t('Back')}")
        default_letter = DRIVER_LETTERS[names.index(default)]
        answer = input(
            f"{t('Choice')} [{default_letter} = {DRIVERS[default].label}] : "
        ).strip()
        if not answer:
            return DRIVERS[default]
        if answer == "0":
            return None
        chosen = match_driver(answer, names)
        if isinstance(chosen, list):
            labels = ", ".join(DRIVERS[name].label for name in chosen)
            print(f"{t('Several technologies match: ')}{labels}")
            return None
        if not chosen:
            print(t("Unknown choice."))
            return None
        return DRIVERS[chosen]

    def _vpn_delete_profile(self):
        name = self._vpn_select_profile()
        if not name:
            return
        if not self._is_yes(
            input(f"{t('Delete profile')} « {name} » ? (y/N) : ")
        ):
            return
        if profiles.delete(name):
            print(f"✓ {t('Profile deleted.')}")
            print(f"  {t('Its vault entry is kept: delete it in KeePassXC.')}")
        else:
            message = t(
                "Not deletable here: this profile comes from a shared"
                " configuration file."
            )
            print(f"✗ {message}")

    # ------------------------------------------------------------------
    # Secrets
    # ------------------------------------------------------------------
    def _vpn_store_secrets(self):
        name = self._vpn_select_profile()
        if not name:
            return
        profile = profiles.load(name)
        driver_cls = get_driver(profile["driver"])
        if driver_cls is None:
            print(f"✗ {t('Unknown driver: ')}{profile['driver']}")
            return
        if not driver_cls.secret_fields:
            print(
                f"{t('No secret to store: this one authenticates over SSH.')}"
            )
            return
        vault = VpnVault(self.config_file, self.kdbx_manager)
        try:
            path = vault.ensure_vault(ask=input)
        except VaultError as error:
            print(f"✗ {error}")
            return
        if not path:
            print(t("No vault: nothing stored."))
            return
        if vault.master_password_is_stored():
            print(f"\n! {t(MASTER_PASSWORD_WARNING)}")

        title = profiles.secret_title(name)
        fields = tuple(key for key, _, _ in driver_cls.secret_fields)
        # Lu AVANT les invites, pour deux raisons : le mot de passe maître
        # est alors demandé avant qu'on tape des secrets, et non après ; et
        # chaque invite peut dire s'il y a déjà quelque chose derrière.
        # « Une réponse vide garde la valeur en place » est un piège quand
        # il n'y a rien en place.
        try:
            existing = vault.read(title, fields=fields)
        except VaultError as error:
            print(f"✗ {error}")
            return

        print(f"\n{t('Vault entry')} : {title}")
        print(f"{t('An empty answer keeps the stored value.')}")
        # Les contraintes du pilote AVANT la première invite : une borne de
        # longueur annoncée après coup coûte une deuxième saisie.
        for note in driver_cls(profile).secret_notes():
            print(f"! {note}")
        print()
        values = {}
        if driver_cls.user_field:
            # Recopié pour que le coffre reste LISIBLE dans KeePassXC ; le
            # profil reste la source de vérité de l'identifiant.
            values["username"] = profile.get(driver_cls.user_field, "")
        for key, label, _required in driver_cls.secret_fields:
            state = t("already set") if existing.get(key) else t("empty")
            secret = self._vpn_ask_secret(f"{t(label)} [{state}]")
            if secret is None:
                return
            if secret:
                values[key] = secret
        try:
            vault.write(title, values)
        except VaultError as error:
            print(f"✗ {error}")
            return
        print(f"\n✓ {t('Secrets stored in the vault.')}")

        # Ce qui reste vide et qui est OBLIGATOIRE : le dire ici, pas au
        # premier montage raté.
        absents = [
            t(label)
            for key, label, required in driver_cls.secret_fields
            if required and not (values.get(key) or existing.get(key))
        ]
        if absents:
            print(
                f"✗ {t('Still missing, the tunnel will not come up: ')}"
                f"{', '.join(absents)}"
            )

    @staticmethod
    def _vpn_ask_secret(label):
        """Un secret, saisi deux fois, jamais affiché.

        Deux fois parce qu'une faute de frappe dans un PSK ne se voit pas :
        elle ressort en « no matching proposal » côté IKE, trois étages plus
        loin, et fait chercher au mauvais endroit pendant une heure.

        Rend "" pour « garder la valeur en place », None pour renoncer.
        """
        first = getpass.getpass(f"{label} : ")
        if not first:
            return ""
        if first != getpass.getpass(f"{t('Confirm')} : "):
            print(f"✗ {t('The two entries differ, nothing stored.')}")
            return None
        return first

    # ------------------------------------------------------------------
    @staticmethod
    def _vpn_ask_flag(label, current):
        """Question oui/non dont le défaut est la valeur ACTUELLE.

        Une réponse vide garde ce qui est en place : rééditer un profil pour
        changer une route ne doit pas remettre le mode de routage à zéro.
        """
        answer = input(f"{label} [{'O/n' if current else 'o/N'}] : ")
        answer = answer.strip().lower()
        if not answer:
            return bool(current)
        return answer in ("y", "yes", "o", "oui")

    @staticmethod
    def _vpn_ask(label, default):
        """Question à réponse par défaut. Vide = on garde `default`."""
        shown = f" [{default}]" if default else ""
        answer = input(f"{label}{shown} : ").strip()
        return answer or default
