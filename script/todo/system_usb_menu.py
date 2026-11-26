#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Sous-menu Système › Clé USB amorçable : détecter les clés, écrire une
image sur l'une d'elles, construire l'ISO ERPLibre Arch Linux, lister les
images prises en charge, gérer les profils machine.

Les faits et les plans viennent de system_usb ; ce fichier les met en
phrases et pose les questions. Rien n'est écrit sur une clé sans trois
gestes : la choisir dans une liste sans défaut, retaper son nom, répondre
oui au plan affiché. lsblk est relu juste avant d'écrire, et le plan
s'arrête si la clé n'est plus la même.

Une ISO ERPLibre peut partir avec un profil machine : il est validé,
résumé, puis placé dans une ISO dérivée (system_usb.plan_remaster) que
l'écriture reçoit à la place de l'ISO choisie. Le profil ne porte aucun
mot de passe ; l'installateur les demande.

Elle peut aussi partir avec un paquet hors ligne, choisi juste après le
profil parmi ceux que la fabrique a rangés (ou fabriqué sur demande) :
l'ISO dérivée le porte en 3e partition. Sa somme est vérifiée avant le
remastering, l'ISO dérivée est contrôlée après (démarrage BIOS et UEFI,
UUID, partition), et une clé trop petite est refusée avec la taille de
clé conseillée.

Mixin de la classe TODO : ses méthodes vivent sur la même instance que
celles des autres fichiers, elles s'appellent donc par « self. ».
"""

import copy
import os
import shlex
import shutil
import sys

import click

from script.iso.archlinux.machine import facts as mf
from script.iso.archlinux.machine import machine_profile as mp
from script.iso.archlinux.machine import profile_messages as pm
from script.todo import system_usb as su
from script.todo.system_menu import entier, octets
from script.todo.todo_i18n import t

# Le navigateur de fichiers demande urwid : sans lui, le menu propose la
# saisie directe d'un chemin.
try:
    from script.todo import todo_file_browser
except Exception:
    todo_file_browser = None

RAISONS_USB = {
    "not-disk": "{device} is not a whole disk.",
    "system": "{device} carries the running system or the repository: it is never written.",
    "not-usb": "{device} is not connected by USB (transport: {transport}).",
    "read-only": "{device} is read-only: check the lock switch of the key or card.",
    "too-small": "{device} ({size}) is smaller than the image ({iso_size}).",
    "too-large": "{device} ({size}) is larger than {limit}: probably an external disk, not a key.",
    "mapped": "{device} has encrypted or LVM volumes open on it ({mapped}): close them first.",
    "iso-on-key": "The image {path} is on the key itself ({mountpoint}): copy it elsewhere first.",
    "not-downloadable": "This image cannot be downloaded.",
    "no-volume-date": "The volume date of {path} cannot be read (blkid, xorriso): the ISO with the profile would not find its boot medium.",
    "no-space": "Not enough free space in {path}: {need} needed, {free} free.",
    "unknown-erplibre-profile": "Unknown ERPLibre profile: {profile}.",
}

# Pourquoi un paquet hors ligne ne peut pas partir sur une clé
# (system_usb.paquet_hors_ligne).
ERREURS_PAQUET = {
    "no-sha256": "no .sha256 file for the image: build the payload again.",
    "manifest-unreadable": "no readable manifest in the image (debugfs, e2fsprogs) nor in payload/.",
    "manifest-invalid": "the manifest is refused by the installer of the key.",
    "record": "this is a recording key, not an offline payload.",
    "report-not-ok": "report.json says a required package is missing or unsigned: build the payload again.",
}

# Les mises en garde d'un paquet pour l'ISO choisie
# (system_usb.alertes_paquet).
ALERTES_PAQUET = {
    "iso-unknown": "Nothing says which ISO recorded this payload: the ISO must have the offline mode, otherwise the key installs online.",
    "other-iso": "This payload was recorded with another ISO (UUID {uuid}): the chosen ISO must have the offline mode, otherwise the key installs online.",
    "archinstall-mismatch": "The ISO carries archinstall {iso}, the payload was recorded with {payload}: it may ask for packages the payload lacks (the installer checks before erasing anything).",
}

# Ce qui manque à une ISO dérivée pour démarrer comme sa base
# (system_usb.defauts_derive).
DEFAUTS_DERIVE = {
    "unreadable": "sfdisk or xorriso cannot read it.",
    "uuid-changed": "its UUID changed: the live would not find its boot medium.",
    "no-bios-boot": "BIOS boot is missing.",
    "no-uefi-boot": "UEFI boot is missing.",
    "no-esp": "the EFI partition is missing.",
    "no-data-partition": "partition 3 (offline payload) is missing or too small.",
}

# Les phrases des codes de validate(), de ProfileError, des mises en
# garde de resolve() et des jetons de plan_summary() : partagées avec
# l'installateur de l'ISO.
RAISONS_PROFIL = pm.REASONS
ALERTES_PROFIL = pm.WARNINGS
JETONS_PROFIL = pm.TOKENS

# L'origine d'un profil, par rang de son dossier dans
# system_usb.dossiers_profils().
ORIGINES_PROFIL = ("repository", "private")

ALERTES_USB = {
    "no-eject": "eject is missing: remove {device} once the commands are done.",
}

# Les détails exprimés en octets, mis en unité lisible avant la phrase.
TAILLES_USB = {"size", "iso_size", "limit", "need", "free"}


def _champs(details):
    """Les détails d'un plan prêts pour str.format_map : tailles en unité
    lisible, valeur absente en « ? »."""
    champs = {}
    for cle, valeur in details.items():
        if cle in TAILLES_USB:
            valeur = octets(valeur)
        champs[cle] = "?" if valeur is None else valeur
    return _Defaut(champs)


class _Defaut(dict):
    """Un champ que la phrase nomme sans que le détail le porte vaut
    « ? » au lieu de lever KeyError."""

    def __missing__(self, cle):
        return "?"


def message_refus(res):
    """La phrase d'un plan refusé."""
    phrase = RAISONS_USB.get(res["reason"], res["reason"] or "")
    return t(phrase).format_map(_champs(res["details"]))


def message_alerte(alerte):
    """La phrase d'une mise en garde de plan."""
    phrase = ALERTES_USB.get(alerte["code"], alerte["code"])
    return t(phrase).format_map(_champs(alerte))


def message_profil(code, details):
    """La phrase d'un code de validation ou d'erreur de profil."""
    phrase = RAISONS_PROFIL.get(code, code)
    return t(phrase).format_map(_Defaut({**{"path": "?"}, **details}))


def message_alerte_profil(alerte):
    """La phrase d'une mise en garde de machine_profile.resolve()."""
    phrase = ALERTES_PROFIL.get(alerte["code"], alerte["code"])
    return t(phrase).format_map(_Defaut(alerte))


def lignes_resume(settings):
    """Le résumé d'un profil, une ligne par libellé traduit. Une valeur
    faite de morceaux séparés par « , » (« 8 GiB, ask ») voit chaque
    morceau qui est un jeton traduit à part."""
    lignes = []
    for libelle, valeur in mp.plan_summary(settings):
        valeur = ", ".join(
            t(JETONS_PROFIL[m]) if m in JETONS_PROFIL else m
            for m in valeur.split(", ")
        )
        lignes.append(f"    {t(libelle)} : {valeur}")
    return lignes


def _retirer(*chemins):
    """Supprime chaque fichier de `chemins` qui existe ; un absent n'est
    pas une erreur."""
    for chemin in chemins:
        try:
            os.remove(chemin)
        except FileNotFoundError:
            pass


def ligne_paquet(paquet, taille_iso=0):
    """Un paquet hors ligne en une ligne : marque, profil, date, taille
    de l'image et taille de clé conseillée pour l'ISO de `taille_iso`
    octets qui le portera."""
    marque = "✗" if paquet["erreurs"] else "✓"
    cle = su.cle_conseillee(su.taille_derive(taille_iso, paquet["taille"]))
    return f"{marque} " + t(
        "payload {profile}, {date}, {size} (key of {key} GB or more)"
    ).format(
        profile=paquet["profil"] or "?",
        date=paquet["date"] or "?",
        size=octets(paquet["taille"]),
        key=cle or "?",
    )


def lignes_cle(cle):
    """La clé en quelques lignes : périphérique, fabricant et modèle,
    taille, numéro de série, transport, amovible, puis chaque partition
    avec son libellé, son système de fichiers et ses montages."""
    nom = " ".join(x for x in (cle["vendor"], cle["model"]) if x) or "?"
    lignes = [f"  {cle['path']}  {nom}  {octets(cle['taille']) or '?'}"]
    lignes.append(
        f"    {t('Serial:')} {cle['serial'] or '?'}"
        f"   {t('Transport:')} {cle['tran'] or '?'}"
        f"   {t('Removable:')} {t('yes') if cle['rm'] else t('no')}"
    )
    if cle["by_id"]:
        lignes.append(f"    {t('by-id:')} {cle['by_id']}")
    if cle["mountpoints"]:
        lignes.append(
            f"    {t('Mounted on:')} {', '.join(cle['mountpoints'])}"
        )
    for p in cle["partitions"]:
        montes = ", ".join(p["mountpoints"]) or t("not mounted")
        lignes.append(
            f"    {p['path']}  {p['label'] or '-'}  {p['fstype'] or '-'}"
            f"  {octets(p['taille']) or '?'}  {montes}"
        )
    return lignes


class SystemUsbMenuMixin:
    def _system_usb(self):
        choices = [
            {
                "prompt_description": t(
                    "Detect USB keys and show their information"
                )
            },
            {"prompt_description": t("Write an ISO to a USB key")},
            {
                "prompt_description": t(
                    "Build the ERPLibre Arch Linux ISO (amd64)"
                )
            },
            {"prompt_description": t("Supported ISO list")},
            {"prompt_description": t("Machine profiles")},
        ]
        help_info = self.fill_help_info(choices)
        while True:
            status = click.prompt(help_info)
            print()
            if status == "0":
                return False
            elif status == "1":
                self._system_usb_detecter()
            elif status == "2":
                self._system_usb_ecrire()
            elif status == "3":
                self._system_usb_construire_iso()
            elif status == "4":
                self._system_usb_catalogue()
            elif status == "5":
                self._system_usb_profils()
            else:
                print(t("Command not found !"))

    # [1] Détecter

    def _system_usb_lire(self):
        """(données lsblk, disques système, clés candidates), ou None si
        lsblk ne répond pas — ce qui est dit."""
        donnees = su.lire_lsblk()
        if donnees is None:
            print(
                f"  ⚠ {t('lsblk did not answer: the disks cannot be listed.')}"
            )
            return None
        systeme = su.disques_systeme(donnees)
        return donnees, systeme, su.cles_usb(donnees, systeme=systeme)

    def _system_usb_detecter(self):
        """Affiche chaque clé candidate et rend leur liste."""
        lu = self._system_usb_lire()
        if lu is None:
            return []
        _donnees, systeme, cles = lu
        if not cles:
            print(f"  {t('No USB key detected: plug one in and retry.')}")
        for cle in cles:
            print("\n".join(lignes_cle(cle)))
            ligne = self._system_usb_ligne_paquet_cle(cle)
            if ligne:
                print(ligne)
        print(
            "  "
            + t("System disks excluded: {count}").format(count=len(systeme))
        )
        print()
        return cles

    def _system_usb_ligne_paquet_cle(self, cle):
        """La ligne qui dit qu'une clé porte un paquet hors ligne, None si
        elle n'en porte pas. Le manifeste n'est lu que si le périphérique
        l'est sans sudo (groupe disk)."""
        partition = su.partition_paquet(cle)
        if partition is None:
            return None
        manifeste = su.manifeste_partition(partition)
        if manifeste is None:
            return "    📦 " + t(
                "Offline payload on {device} (manifest readable as root only)."
            ).format(device=partition["path"])
        return "    📦 " + t(
            "Offline payload on {device}: {profile}, {date}"
        ).format(
            device=partition["path"],
            profile=manifeste.get("erplibre_profile") or "?",
            date=str(manifeste.get("created") or "?")[:10],
        )

    # [2] Écrire

    def _system_usb_ecrire(self):
        """Choisir l'image, choisir la clé, retaper son nom, voir le plan,
        dire oui ; puis relire lsblk et écrire. Rend vrai si tout a
        réussi."""
        iso = self._system_usb_choisir_iso()
        if not iso:
            return False
        iso_taille = self._system_usb_valider_iso(iso)
        if iso_taille is None:
            return False
        self._usb_paquet = None
        if su.est_iso_erplibre(iso):
            derive = self._system_usb_iso_avec_profil(iso)
            if not derive:
                return False
            if derive != iso:
                iso = derive
                iso_taille = self._system_usb_valider_iso(iso)
                if iso_taille is None:
                    return False
        lu = self._system_usb_lire()
        if lu is None:
            return False
        _donnees, systeme, cles = lu
        if not cles:
            print(f"  {t('No USB key detected: plug one in and retry.')}")
            return False
        cle = self._system_usb_choisir_cle(cles)
        if cle is None:
            return False
        print("\n".join(lignes_cle(cle)))
        print(f"\n⚠ {t('This key will be erased:')} {cle['nom']}")
        if (
            input(f"💬 {t('Type its name to confirm: ')}").strip()
            != cle["nom"]
        ):
            print(t("Nothing to do."))
            return False
        res = su.plan_ecriture(cle, iso, iso_taille, systeme)
        if not res["ok"]:
            print(f"  ⚠ {message_refus(res)}")
            if res["reason"] == "too-small" and self._usb_paquet:
                self._system_usb_conseil_cle(iso_taille)
            return False
        for alerte in res["warnings"]:
            print(f"  ⚠ {message_alerte(alerte)}")
        for cmd in res["plan"]:
            print(f"  {t('Will execute:')} {shlex.join(cmd)}")
        print(
            "  ⚠ "
            + t("ALL DATA on {device} will be erased.").format(
                device=cle["path"]
            )
        )
        if not self._is_yes(
            input(t("Erase the key and write the image? (y/N): "))
        ):
            print(f"  {t('Nothing changed.')}")
            return False
        if not self._system_usb_toujours_la(cle, iso, iso_taille, res):
            return False
        if not self._system_usb_executer(res["plan"]):
            return False
        print(
            f"  ✓ {t('The key is ready: boot the computer from it (the boot menu key is often F12, F11, F8 or Esc).')}"
        )
        print()
        return True

    def _system_usb_toujours_la(self, cle, iso, iso_taille, res):
        """Relit lsblk juste avant d'écrire : la clé doit être la même
        (chemin, série, taille, modèle), ses montages et mappages
        inchangés, et le plan qu'on en tire identique à celui qui a été
        confirmé. Un montage apparu entre-temps, ou une autre clé sur le
        même /dev/sdX, arrête tout."""
        donnees = su.lire_lsblk()
        apres = (
            su.trouver(su.disques(donnees), cle["path"]) if donnees else None
        )
        if apres is not None and su.meme_cle(cle, apres):
            systeme = su.disques_systeme(donnees)
            relu = su.plan_ecriture(apres, iso, iso_taille, systeme)
            if (
                relu["ok"]
                and relu["plan"] == res["plan"]
                and su.occupation(apres) == su.occupation(cle)
            ):
                return True
        print(
            f"  ⚠ {t('The key changed since the confirmation (unplugged, swapped or mounted): nothing was written.')}"
        )
        return False

    def _system_usb_choisir_cle(self, cles):
        """Le numéro d'une clé, sans défaut : une réponse vide repose la
        question, « 0 » annule."""
        for i, cle in enumerate(cles, 1):
            nom = " ".join(x for x in (cle["vendor"], cle["model"]) if x)
            print(
                f"  [{i}] {cle['nom']}  {nom or '?'}"
                f"  {octets(cle['taille']) or '?'}"
            )
        while True:
            reponse = input(t("Key number (0 to cancel): ")).strip()
            if reponse == "0":
                return None
            numero = entier(reponse)
            if numero is not None and 1 <= numero <= len(cles):
                return cles[numero - 1]
            print(f"  {t('Choose a number from the list.')}")

    def _system_usb_valider_iso(self, chemin):
        """La taille de l'image si le fichier existe et n'est pas vide ;
        None sinon, ce qui est dit. Une extension inconnue n'est qu'une
        mise en garde : une image brute peut porter n'importe quel nom."""
        if not os.path.isfile(chemin):
            print(f"❌ {t('No such file: ')}{chemin}")
            return None
        taille = os.path.getsize(chemin)
        if taille <= 0:
            print(f"❌ {t('The file is empty:')} {chemin}")
            return None
        if not su.extension_image(chemin):
            print(
                f"  ⚠ {t('This file does not end in .iso or .img: make sure it is a disk image.')}"
            )
        print(f"  {t('Image:')} {chemin} ({octets(taille)})")
        return taille

    def _system_usb_choisir_iso(self):
        """Le chemin de l'image, par le navigateur de fichiers ou le
        catalogue ; None si l'on annule."""
        print(f"  [1] {t('Browse files')}")
        print(f"  [2] {t('Supported ISO list')}")
        reponse = input(t("Choice, Enter to cancel: ")).strip()
        if reponse == "1":
            return self._system_usb_parcourir()
        if reponse == "2":
            return self._system_usb_iso_catalogue()
        return None

    def _system_usb_depart(self):
        """Le dossier où le navigateur s'ouvre : celui des ISO, sinon
        ~/Downloads, sinon le dossier personnel."""
        for dossier in (
            su.dossier_iso(),
            os.path.expanduser("~/Downloads"),
        ):
            if os.path.isdir(dossier):
                return dossier
        return os.path.expanduser("~")

    def _system_usb_selection(self, chemin):
        self._usb_selection = chemin

    def _system_usb_parcourir(self):
        """Le parcours d'abord ; une saisie directe si urwid manque ou si
        l'on en sort sans rien choisir."""
        if todo_file_browser is not None:
            self._usb_selection = ""
            navigateur = todo_file_browser.FileBrowser(
                self._system_usb_depart(), self._system_usb_selection
            )
            navigateur.run_main_frame()
            if self._usb_selection and os.path.isfile(self._usb_selection):
                print(self._usb_selection)
                return self._usb_selection
        reponse = input(t("Path to the image (empty to cancel): ")).strip()
        if not reponse:
            return None
        return os.path.expanduser(reponse)

    def _system_usb_iso_catalogue(self):
        """Une image du catalogue : une entrée locale rend son fichier,
        une entrée « url » se télécharge et se vérifie d'abord. Une entrée
        non disponible n'est pas sélectionnable."""
        entrees = su.catalogue()
        self._system_usb_afficher_catalogue(entrees, numeros=True)
        numero = entier(input(t("Image number, Enter to cancel: ")).strip())
        if numero is None or not 1 <= numero <= len(entrees):
            return None
        entree = entrees[numero - 1]
        if not entree["disponible"]:
            print(f"  ✗ {t(entree['raison_key'])}")
            return None
        if entree["source"] == "url":
            return self._system_usb_telecharger(entree)
        return entree["chemin"]

    def _system_usb_telecharger(self, entree):
        """Télécharge une image du catalogue et vérifie sa somme SHA-256.

        La liste des sommes vient d'abord : une image déjà présente et
        juste n'est pas retéléchargée. Sinon l'image arrive dans un
        « .part », renommé seulement si sa somme est la bonne ; une somme
        fausse le supprime (voir system_usb.plan_telechargement)."""
        res = su.plan_telechargement(entree)
        if not res["ok"]:
            print(f"  ⚠ {message_refus(res)}")
            return None
        details = res["details"]
        for cmd in res["plan"]:
            print(f"  {t('Will execute:')} {shlex.join(cmd)}")
        if not self._is_yes(input(t("Download now? (y/N): "))):
            print(f"  {t('Nothing changed.')}")
            return None
        os.makedirs(os.path.dirname(details["path"]), exist_ok=True)
        sommes, image = res["plan"]
        if not self._system_usb_executer([sommes]):
            return None
        try:
            with open(details["sums"], encoding="utf-8") as fh:
                texte_sommes = fh.read()
        except OSError:
            texte_sommes = ""
        attendue = su.parse_sha256sums(texte_sommes, details["file"])
        if attendue is None:
            print(
                "  ⚠ "
                + t("The checksum list has no line for {file}.").format(
                    file=details["file"]
                )
            )
            return None
        if (
            os.path.isfile(details["path"])
            and su.sha256_fichier(details["path"]) == attendue
        ):
            print(
                f"  ✓ {t('Already downloaded and verified:')} {details['path']}"
            )
            return details["path"]
        if not self._system_usb_executer([image]):
            return None
        print(f"  {t('Checking the SHA-256 checksum…')}")
        if su.sha256_fichier(details["partial"]) != attendue:
            try:
                os.remove(details["partial"])
            except OSError:
                pass
            print(
                f"  ⚠ {t('The SHA-256 checksum does not match: the download is deleted, retry later.')}"
            )
            return None
        os.replace(details["partial"], details["path"])
        print(f"  ✓ {t('Checksum verified:')} {details['path']}")
        return details["path"]

    def _system_usb_executer(self, plan):
        """Lance chaque commande du plan ; la première qui échoue, ou un
        Ctrl-C, arrête la suite, listée comme non lancée. Rend vrai si
        tout a réussi."""
        for i, cmd in enumerate(plan):
            # Chaque étape suppose la précédente faite : dd sur une clé
            # encore montée, ou cmp après un dd interrompu, n'ont pas de
            # sens.
            try:
                statut = self.execute.exec_command_live(
                    shlex.join(cmd), source_erplibre=False
                )
                message = t("Command failed:")
            except KeyboardInterrupt:
                statut = 1
                message = t("Interrupted at:")
            if statut:
                print(f"\n  ⚠ {message} {shlex.join(cmd)}")
                suite = plan[i + 1 :]
                if suite:
                    print(f"  {t('Not run:')}")
                    for reste in suite:
                        print(f"    {shlex.join(reste)}")
                return False
        return True

    # [3] Construire

    def _system_usb_construire_iso(self):
        """Lance le constructeur de l'ISO ERPLibre Arch Linux s'il est dans
        le dépôt. Absent, cette méthode dit seulement qu'il ne l'est pas :
        c'est le point d'accroche du constructeur, livré à part.

        Le constructeur tourne sous le Python du venv d'outillage, ou à
        défaut sous celui qui fait tourner le TODO : un checkout sans venv
        (le TODO de la clé ERPLibre, sur le Python du live) obtient ainsi
        le refus explicite du constructeur — aucun moteur de conteneur —
        au lieu d'un interpréteur introuvable."""
        script = os.path.join(su.RACINE_DEPOT, su.SCRIPT_CONSTRUCTION)
        if not os.path.isfile(script):
            print(
                f"  {t('The ERPLibre Arch Linux ISO builder is not available yet in this checkout:')} {su.SCRIPT_CONSTRUCTION}"
            )
            return False
        commande = shlex.join(
            [self._system_usb_python(), su.SCRIPT_CONSTRUCTION]
        )
        return not self.execute.exec_command_live(
            commande, source_erplibre=False
        )

    def _system_usb_python(self):
        """Le Python du venv d'outillage, relatif à la racine du dépôt, ou
        à défaut celui qui fait tourner le TODO."""
        python = os.path.join(".venv.erplibre", "bin", "python")
        if not os.access(os.path.join(su.RACINE_DEPOT, python), os.X_OK):
            python = sys.executable
        return python

    # [4] Catalogue

    def _system_usb_afficher_catalogue(self, entrees, numeros=False):
        for i, e in enumerate(entrees, 1):
            tete = f"  [{i}] " if numeros else "  "
            marque = "✓" if e["disponible"] else "✗"
            print(f"{tete}{marque} {t(e['libelle_key'])}")
            if not e["disponible"]:
                print(f"      {t(e['raison_key'])}")
            elif e["source"] == "url":
                if e["chemin"] and os.path.isfile(e["chemin"]):
                    print(f"      {t('Downloaded:')} {e['chemin']}")
                else:
                    print(
                        f"      {t('Downloaded on demand from:')} {e['url']}"
                    )
            elif e["chemin"]:
                print(f"      {e['chemin']}")

    def _system_usb_catalogue(self):
        self._system_usb_afficher_catalogue(su.catalogue())
        paquets = su.paquets_hors_ligne()
        print(
            "  "
            + t("Offline payloads in {path}:").format(
                path=su.dossier_paquets()
            )
        )
        if not paquets:
            print(
                f"    {t('none: build one when writing an ERPLibre ISO to a key.')}"
            )
        self._system_usb_afficher_paquets(paquets, numeros=False)
        print()

    # [2] Écrire, avec un profil machine

    def _system_usb_iso_avec_profil(self, iso):
        """L'image à écrire quand `iso` est une ISO ERPLibre : `iso` elle-même
        si l'on ne choisit ni profil (installation guidée) ni paquet hors
        ligne, l'ISO dérivée qui porte ce qu'on a choisi, ou None si l'on
        annule ou qu'un pas échoue. Le paquet choisi reste dans
        self._usb_paquet pour la suite de l'écriture."""
        profil = self._system_usb_choisir_profil()
        if profil is False:
            return None
        paquet = self._system_usb_choisir_paquet(iso)
        self._usb_paquet = paquet
        if profil is None and paquet is None:
            return iso
        return self._system_usb_remaster(iso, profil, paquet)

    def _system_usb_choisir_profil(self):
        """Le profil machine effectif choisi, None pour aucun, False si le
        profil choisi a des erreurs."""
        entrees = mp.list_profiles(su.dossiers_profils())
        print(f"  {t('Machine profile:')}")
        print(f"  [0] {t('none (guided installation)')}")
        self._system_usb_profils_afficher(entrees, erreurs=False)
        while True:
            reponse = input(t("Profile number, Enter for none: ")).strip()
            if reponse in ("", "0"):
                return None
            numero = entier(reponse)
            if numero is not None and 1 <= numero <= len(entrees):
                break
            print(f"  {t('Choose a number from the list.')}")
        entree = entrees[numero - 1]
        if entree["errors"] or entree["effective"] is None:
            print(
                f"  ⚠ {t('This profile has errors: fix it before writing.')}"
            )
            for code, details in entree["errors"]:
                print(f"    {message_profil(code, details)}")
            return False
        profil = entree["effective"]
        print("\n".join(lignes_resume(profil)))
        print(
            f"  🔒 {t('Passwords and LUKS passphrases will be asked during installation.')}"
        )
        return profil

    # [2] Écrire, avec un paquet hors ligne

    def _system_usb_afficher_paquets(
        self, paquets, numeros=True, taille_iso=0
    ):
        """Une ligne par paquet (ligne_paquet), son dossier et ses erreurs
        dessous."""
        for i, p in enumerate(paquets, 1):
            tete = f"  [{i}] " if numeros else "    "
            print(f"{tete}{ligne_paquet(p, taille_iso)}")
            print(f"      {p['dossier']}")
            for code in p["erreurs"]:
                print(f"      ⚠ {t(ERREURS_PAQUET.get(code, code))}")

    def _system_usb_choisir_paquet(self, iso):
        """Le paquet hors ligne que la clé portera (un dict de
        system_usb.paquets_hors_ligne), ou None pour aucun (installation
        en ligne). L'entrée qui suit la liste lance la fabrique ; après
        elle, ou après un paquet qu'on ne garde pas, la liste est relue."""
        while True:
            paquets = su.paquets_hors_ligne()
            print(f"  {t('Offline installation:')}")
            print(f"  [0] {t('no (network required during installation)')}")
            self._system_usb_afficher_paquets(
                paquets, taille_iso=os.path.getsize(iso)
            )
            fabrique = len(paquets) + 1
            print(
                f"  [{fabrique}] {t('Build an offline payload (reference install in QEMU)…')}"
            )
            reponse = input(t("Payload number, Enter for none: ")).strip()
            if reponse in ("", "0"):
                return None
            numero = entier(reponse)
            if numero == fabrique:
                self._system_usb_fabriquer_paquet(iso)
                continue
            if numero is None or not 1 <= numero <= len(paquets):
                print(f"  {t('Choose a number from the list.')}")
                continue
            paquet = paquets[numero - 1]
            if paquet["erreurs"]:
                print(
                    f"  ⚠ {t('This payload cannot go on a key: see the reasons above.')}"
                )
                continue
            if self._system_usb_accepter_paquet(iso, paquet):
                return paquet

    def _system_usb_accepter_paquet(self, iso, paquet):
        """Montre la taille de clé conseillée et les mises en garde du
        paquet pour `iso` (system_usb.alertes_paquet), puis, s'il y en a,
        ou si aucune clé branchée n'est assez grande, demande de garder le
        paquet. Rend vrai si on le garde."""
        attendue = su.taille_derive(os.path.getsize(iso), paquet["taille"])
        self._system_usb_conseil_cle(attendue)
        alertes = su.alertes_paquet(
            paquet, su.lire_pkglist(iso), su.lire_uuid_iso(iso)
        )
        for alerte in alertes:
            phrase = ALERTES_PAQUET.get(alerte["code"], alerte["code"])
            print(f"  ⚠ {t(phrase).format_map(_Defaut(alerte))}")
        petites = self._system_usb_cles_trop_petites(attendue)
        if petites:
            print(
                "  ⚠ "
                + t(
                    "No USB key plugged in can hold {size}: the largest is {largest}."
                ).format(size=octets(attendue), largest=octets(petites))
            )
        if (alertes or petites) and not self._is_yes(
            input(t("Keep this offline payload? (y/N): "))
        ):
            print(f"  {t('Nothing changed.')}")
            return False
        return True

    def _system_usb_conseil_cle(self, taille):
        """La taille de clé conseillée pour une image de `taille` octets,
        et la durée d'une écriture de cette taille."""
        print(
            "  💾 "
            + t(
                "The image will take {size}: use a key of {key} GB or more. Writing and reading it back takes tens of minutes on a slow key."
            ).format(size=octets(taille), key=su.cle_conseillee(taille) or "?")
        )

    def _system_usb_cles_trop_petites(self, taille):
        """La taille de la plus grande clé branchée si aucune ne reçoit
        `taille` octets, None sinon (ou sans clé, ou sans lsblk) : c'est
        alors avant la fabrication de l'ISO dérivée qu'il faut le dire."""
        donnees = su.lire_lsblk()
        if donnees is None:
            return None
        tailles = [c["taille"] or 0 for c in su.cles_usb(donnees)]
        if not tailles or max(tailles) >= taille:
            return None
        return max(tailles)

    def _system_usb_fabriquer_paquet(self, iso):
        """Fabrique un paquet hors ligne depuis `iso` après le choix d'un
        profil ERPLibre, l'annonce de sa durée et de sa place, et un oui.
        Rend vrai si la fabrique a réussi."""
        for i, profil in enumerate(su.PROFILS_ERPLIBRE, 1):
            print(f"  [{i}] {profil}")
        numero = entier(
            input(t("ERPLibre profile number (0 to cancel): ")).strip()
        )
        if numero is None or not 1 <= numero <= len(su.PROFILS_ERPLIBRE):
            return False
        profil = su.PROFILS_ERPLIBRE[numero - 1]
        dossier = su.dossier_paquets()
        graine = su.GRAINE_GIT if os.path.isdir(su.GRAINE_GIT) else None
        res = su.plan_fabrique(
            profil,
            iso,
            self._system_usb_python(),
            dossier,
            graine=graine,
            libre=su.espace_libre(dossier),
        )
        if not res["ok"]:
            print(f"  ⚠ {message_refus(res)}")
            return False
        details = res["details"]
        print(
            "  ⏱ "
            + t(
                "About {minutes} min and up to {need} in {path}: a reference install of {profile} in QEMU (KVM, no root), network required during the build."
            ).format(
                minutes=details["minutes"],
                need=octets(details["need"]),
                path=dossier,
                profile=profil,
            )
        )
        if details["seed"]:
            print(f"  {t('Git mirrors copied first from:')} {details['seed']}")
        for cmd in res["plan"]:
            print(f"  {t('Will execute:')} {shlex.join(cmd)}")
        if not self._is_yes(
            input(t("Build the offline payload now? (y/N): "))
        ):
            print(f"  {t('Nothing changed.')}")
            return False
        return self._system_usb_executer(res["plan"])

    def _system_usb_verifier_paquet(self, paquet):
        """Vrai si l'image du paquet a encore la somme de son .sha256."""
        print(f"  {t('Checking the SHA-256 of the offline payload image…')}")
        if su.sha256_fichier(paquet["image"]) == paquet["sha256"]:
            return True
        print(
            f"  ⚠ {t('The offline payload image does not match its .sha256: build the payload again.')}"
        )
        return False

    def _system_usb_remaster(self, iso, profil, paquet=None):
        """Le chemin de l'ISO dérivée qui porte `profil` et/ou `paquet`,
        fabriquée par xorriso selon system_usb.plan_remaster après un oui,
        ou reprise telle quelle si une précédente est intacte ; None
        sinon.

        Rien n'est écrit avant le oui. Le dossier des dérivées est en
        0700 et l'ISO passe en 0600 : elle nomme un utilisateur et un
        hôte, et le paquet porte la clé de son autorité. Le profil n'est
        écrit en JSON que le temps de xorriso, qui le recopie dans l'ISO.
        La place libre est vérifiée d'abord, en comptant les dérivées
        périmées, retirées avant xorriso s'il le faut ; la somme du paquet
        l'est après le oui. Sa somme SHA-256 n'est écrite qu'une fois
        xorriso réussi et l'ISO contrôlée ; un échec retire l'ISO
        partielle. Une erreur du système de fichiers (disque plein, quota)
        devient une mise en garde."""
        if not self._system_usb_xorriso():
            return None
        print(f"  {t('Computing the SHA-256 of the image…')}")
        sha_base = su.sha256_fichier(iso)
        if sha_base is None:
            print(f"❌ {t('No such file: ')}{iso}")
            return None
        texte = mp.dump(profil) if profil is not None else None
        derive = su.chemin_derive(
            su.dossier_derives(),
            sha_base,
            su.sha256_texte(texte) if texte else None,
            paquet["sha256"] if paquet else None,
        )
        if su.derive_valide(derive):
            deja = (
                "Already built with this offline payload:"
                if paquet
                else "Already built with this profile:"
            )
            print(f"  ✓ {t(deja)} {derive}")
            return derive
        profil_json = os.path.splitext(derive)[0] + ".json" if texte else None
        res = su.plan_remaster(
            iso,
            profil_json,
            derive,
            su.lire_volume_date(iso),
            image_paquet=paquet["image"] if paquet else None,
        )
        if not res["ok"]:
            print(f"  ⚠ {message_refus(res)}")
            return None
        dossier = os.path.dirname(derive)
        besoin = su.taille_derive(
            os.path.getsize(iso), paquet["taille"] if paquet else 0
        )
        perimes = su.derives_perimes(dossier, derive)
        verdict = su.verdict_espace(
            besoin,
            su.espace_libre(dossier),
            sum(os.path.getsize(f) for f in perimes),
        )
        if verdict == "no-space":
            print(
                "  ⚠ "
                + message_refus(
                    {
                        "reason": "no-space",
                        "details": {
                            "path": dossier,
                            "need": besoin,
                            "free": su.espace_libre(dossier),
                        },
                    }
                )
            )
            return None
        if verdict == "cleanup":
            print(
                f"  {t('Outdated derived ISO files are removed first to make room.')}"
            )
        for cmd in res["plan"]:
            print(f"  {t('Will execute:')} {shlex.join(cmd)}")
        question = (
            "Build the ISO with the offline payload? (y/N): "
            if paquet
            else "Build the ISO with this profile? (y/N): "
        )
        if not self._is_yes(input(t(question))):
            print(f"  {t('Nothing changed.')}")
            return None
        try:
            if verdict == "cleanup":
                self._system_usb_retirer_perimes(perimes)
            if paquet and not self._system_usb_verifier_paquet(paquet):
                return None
            return self._system_usb_remaster_executer(
                res["plan"],
                profil_json,
                texte,
                derive,
                volume_date=res["details"]["volume_date"],
                image_octets=paquet["taille"] if paquet else None,
            )
        except OSError as exc:
            print(f"  ⚠ {t('File system error:')} {exc}")
            _retirer(derive, su.chemin_somme(derive))
            return None
        finally:
            if profil_json:
                _retirer(profil_json)

    def _system_usb_retirer_perimes(self, perimes):
        for perime in perimes:
            _retirer(perime)
            print(f"  {t('Removed an outdated derived ISO file:')} {perime}")

    def _system_usb_remaster_executer(
        self,
        plan,
        profil_json,
        texte,
        derive,
        volume_date=None,
        image_octets=None,
    ):
        """Écrit le profil s'il y en a un, lance `plan`, contrôle l'ISO
        dérivée (system_usb.defauts_derive), la scelle (0600, somme) et
        retire les dérivées périmées. Rend `derive`, ou None si xorriso
        échoue ou que le contrôle trouve un défaut. Les OSError remontent
        à _system_usb_remaster."""
        su.dossier_prive(os.path.dirname(derive))
        if texte is not None:
            su.ecrire_atomique(profil_json, texte)
        _retirer(derive, su.chemin_somme(derive))
        if not self._system_usb_executer(plan):
            _retirer(derive)
            return None
        if not os.path.isfile(derive):
            print(f"  ⚠ {t('xorriso did not produce the ISO:')} {derive}")
            return None
        defauts = su.defauts_derive(
            su.lire_faits_derive(derive), volume_date, image_octets
        )
        if defauts:
            print(f"  ⚠ {t('The derived ISO is refused:')} {derive}")
            for code in defauts:
                print(f"    {t(DEFAUTS_DERIVE.get(code, code))}")
            _retirer(derive)
            return None
        ligne = su.ligne_somme(derive)
        if ligne is None:
            print(f"  ⚠ {t('xorriso did not produce the ISO:')} {derive}")
            _retirer(derive)
            return None
        os.chmod(derive, 0o600)
        su.ecrire_atomique(su.chemin_somme(derive), ligne)
        print(f"  ✓ {t('Derived ISO:')} {derive}")
        self._system_usb_retirer_perimes(
            su.derives_perimes(os.path.dirname(derive), derive)
        )
        return derive

    def _system_usb_xorriso(self):
        """Vrai si xorriso est là, ou vient d'être installé après un oui.
        La commande d'installation est montrée en entier avant la
        question, sudo compris."""
        if shutil.which("xorriso"):
            return True
        from script.todo.qemu_privilege import install_cmd_for

        print(
            f"  ⚠ {t('xorriso is missing: it builds the ISO that carries the profile.')}"
        )
        cmd, _paquet = install_cmd_for(su.PAQUETS_XORRISO)
        if not cmd:
            print(f"  {t('unknown package manager')}")
            return False
        print(f"  {t('Will run, as root:')} {cmd}")
        if not self._is_yes(input(t("Install xorriso now? (y/N): "))):
            print(f"  {t('Nothing changed.')}")
            return False
        self.execute.exec_command_live(cmd, source_erplibre=False)
        return shutil.which("xorriso") is not None

    # [5] Profils machine

    def _system_usb_profils(self):
        choices = [
            {"prompt_description": t("List machine profiles")},
            {"prompt_description": t("Duplicate a profile into private/")},
            {"prompt_description": t("Edit a private profile")},
            {"prompt_description": t("Delete a private profile")},
            {
                "prompt_description": t(
                    "Preview « auto » on this computer (host, not the target)"
                )
            },
            {"prompt_description": t("Show a profile summary")},
        ]
        help_info = self.fill_help_info(choices)
        actions = {
            "1": self._system_usb_profils_lister,
            "2": self._system_usb_profil_dupliquer,
            "3": self._system_usb_profil_editer,
            "4": self._system_usb_profil_supprimer,
            "5": self._system_usb_profil_apercu,
            "6": self._system_usb_profil_resume,
        }
        while True:
            status = click.prompt(help_info)
            print()
            if status == "0":
                return False
            action = actions.get(status)
            if action is None:
                print(t("Command not found !"))
            else:
                action()

    def _system_usb_profils_afficher(self, entrees, erreurs=True):
        """Une ligne par profil : numéro, nom, origine ; ses erreurs
        dessous si `erreurs`, sinon une marque ✗."""
        for i, e in enumerate(entrees, 1):
            origine = t(ORIGINES_PROFIL[min(e["dir"], 1)])
            marque = "✗" if e["errors"] else "✓"
            print(f"  [{i}] {marque} {e['name']}  ({origine})")
            if erreurs:
                print(f"      {e['path']}")
                for code, details in e["errors"]:
                    print(f"      ⚠ {message_profil(code, details)}")

    def _system_usb_profils_lister(self):
        entrees = mp.list_profiles(su.dossiers_profils())
        if not entrees:
            print(f"  {t('No machine profile found.')}")
        self._system_usb_profils_afficher(entrees)
        print()
        return entrees

    def _system_usb_profil_choisir(self, prives=False):
        """Un profil choisi par son numéro, ou None ; `prives` ne propose
        que ceux du dossier privé."""
        entrees = mp.list_profiles(su.dossiers_profils())
        if prives:
            entrees = [e for e in entrees if e["dir"] >= 1]
        if not entrees:
            print(
                f"  {t('No private profile: duplicate one first.')}"
                if prives
                else f"  {t('No machine profile found.')}"
            )
            return None
        self._system_usb_profils_afficher(entrees, erreurs=False)
        numero = entier(input(t("Profile number (0 to cancel): ")).strip())
        if numero is None or not 1 <= numero <= len(entrees):
            return None
        return entrees[numero - 1]

    def _system_usb_profil_dupliquer(self):
        """Copie un profil dans le dossier privé sous un nom neuf. Rend le
        chemin écrit, ou None."""
        entree = self._system_usb_profil_choisir()
        if entree is None:
            return None
        if entree["raw"] is None:
            print(
                f"  ⚠ {t('This profile has errors: fix it before writing.')}"
            )
            return None
        nom = input(t("New profile name (empty to cancel): ")).strip()
        if not nom:
            return None
        nom = mp.slug(nom)
        if mp.find(nom, su.dossiers_profils()):
            print(
                "  ⚠ "
                + t("A profile named {name} already exists.").format(name=nom)
            )
            return None
        brut = copy.deepcopy(entree["raw"])
        brut["name"] = nom
        brut["schema"] = mp.SCHEMA_VERSION
        return self._system_usb_profil_enregistrer(brut)

    def _system_usb_profil_enregistrer(self, brut, chemin=None):
        """Valide `brut` seul puis complété de ses ancêtres, et l'écrit
        s'il n'a aucune erreur : dans `chemin` (le fichier qu'on édite), ou
        dans le dossier privé sous le nom du profil. Rend le chemin écrit,
        ou None ; une erreur du système de fichiers devient une mise en
        garde."""
        try:
            erreurs = mp.validate(brut) + mp.validate(
                mp.effective(brut, su.dossiers_profils())
            )
        except mp.ProfileError as exc:
            erreurs = [(exc.code, exc.details)]
        if erreurs:
            print(f"  ⚠ {t('Not saved: the profile has errors.')}")
            for code, details in erreurs:
                print(f"    {message_profil(code, details)}")
            return None
        try:
            chemin = su.enregistrer_profil(brut, chemin=chemin)
        except OSError as exc:
            print(f"  ⚠ {t('File system error:')} {exc}")
            return None
        print(f"  ✓ {t('Saved:')} {chemin}")
        return chemin

    def _system_usb_profil_editer(self):
        """Édite un profil privé section par section, puis l'enregistre
        s'il reste valide. Rend le chemin écrit, ou None."""
        entree = self._system_usb_profil_choisir(prives=True)
        if entree is None or entree["raw"] is None:
            return None
        brut = copy.deepcopy(entree["raw"])
        print(
            f"  {t('Enter keeps the current value; « auto » and « ask » are accepted where the field allows them.')}"
        )
        while True:
            for i, section in enumerate(mp.SECTIONS, 1):
                print(f"  [{i}] {section}")
            numero = entier(input(t("Section number (0 to finish): ")).strip())
            if numero is None or numero == 0:
                break
            if 1 <= numero <= len(mp.SECTIONS):
                self._system_usb_profil_section(brut, mp.SECTIONS[numero - 1])
        if brut == entree["raw"]:
            print(f"  {t('Nothing changed.')}")
            return None
        return self._system_usb_profil_enregistrer(brut, chemin=entree["path"])

    def _system_usb_profil_section(self, brut, section):
        """Pose chaque champ de `section` : Entrée garde la valeur, une
        réponse que validate() refuse repose la question. Les changements
        s'écrivent dans `brut`."""
        for chemin in mp.section_fields(section):
            try:
                complet = mp.effective(brut, su.dossiers_profils())
            except mp.ProfileError:
                complet = mp.merge(mp.DEFAULTS, brut)
            actuel = mp.display_value(mp.get(complet, chemin))
            while True:
                reponse = input(f"  {chemin} [{actuel}]: ")
                if not reponse.strip():
                    break
                try:
                    valeur = mp.parse_value(chemin, reponse)
                except ValueError:
                    print(
                        "  ⚠ "
                        + t("Invalid value for {path}.").format(path=chemin)
                    )
                    continue
                essai = mp.put(copy.deepcopy(brut), chemin, valeur)
                erreurs = [
                    (code, d)
                    for code, d in mp.validate(essai)
                    if str(d.get("path", "")).startswith(chemin)
                ]
                if erreurs:
                    for code, details in erreurs:
                        print(f"  ⚠ {message_profil(code, details)}")
                    continue
                mp.put(brut, chemin, valeur)
                break

    def _system_usb_profil_supprimer(self):
        """Supprime un profil privé après qu'on a retapé son nom."""
        entree = self._system_usb_profil_choisir(prives=True)
        if entree is None:
            return False
        print(f"\n⚠ {t('This profile will be deleted:')} {entree['name']}")
        if (
            input(f"💬 {t('Type its name to confirm: ')}").strip()
            != (entree["name"])
        ):
            print(t("Nothing to do."))
            return False
        os.remove(entree["path"])
        print(f"  ✓ {t('Deleted:')} {entree['path']}")
        return True

    def _system_usb_profil_resume(self):
        """Le résumé d'un profil tel qu'écrit : « auto » et « ask » y
        restent, ils se décident sur la cible."""
        entree = self._system_usb_profil_choisir()
        if entree is None:
            return None
        if entree["effective"] is None:
            for code, details in entree["errors"]:
                print(f"  ⚠ {message_profil(code, details)}")
            return None
        print("\n".join(lignes_resume(entree["effective"])))
        for code, details in entree["errors"]:
            print(f"  ⚠ {message_profil(code, details)}")
        print()
        return entree["effective"]

    def _system_usb_profil_apercu(self):
        """Résout un profil sur les faits de CET ordinateur. Ce n'est
        qu'un aperçu : la cible a son propre matériel, et l'installateur
        refait la résolution sur elle."""
        entree = self._system_usb_profil_choisir()
        if entree is None:
            return None
        if entree["errors"] or entree["effective"] is None:
            for code, details in entree["errors"]:
                print(f"  ⚠ {message_profil(code, details)}")
            return None
        faits = mf.facts_from(mf.snapshot())
        reglages, questions = mp.resolve(entree["effective"], faits)
        print(f"  🖥 {t('This computer (host, not the target):')}")
        print("\n".join(lignes_resume(reglages)))
        for alerte in reglages["warnings"]:
            print(f"  ⚠ {message_alerte_profil(alerte)}")
        if questions:
            print(
                f"  {t('Asked during installation:')} {', '.join(questions)}"
            )
        print()
        return reglages
