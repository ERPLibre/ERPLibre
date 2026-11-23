#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Menu QEMU/KVM : KSM, le partage des pages identiques de la station.

KSM (Kernel Samepage Merging) fusionne les pages de mémoire identiques des
VM : un hôte qui fait tourner plusieurs invités du même système, ou un
hyperviseur imbriqué, y regagne de la mémoire au prix d'un peu de processeur.
QEMU marque la mémoire de ses invités comme fusionnable ; il reste à lancer
le démon du noyau, ce que fait « run ».

Deux réglages indépendants, et l'écran les montre séparément :

* « run », dans sysfs, vaut pour le noyau EN COURS et s'efface au
  redémarrage ;
* la permanence est un fichier systemd-tmpfiles qui réécrit « run » à chaque
  démarrage. Le retirer ne change rien à l'état courant.

L'état se lit sans privilège. Tout changement passe par sudo, et la commande
est montrée avant de partir. Le verdict vient de l'état RELU après coup : le
code de retour dit seulement si la commande s'est plainte.

Les chemins, sudo et l'exécuteur sont des paramètres : les tests pointent les
fonctions de ce fichier vers des fichiers temporaires, sans root ni vrai
sysfs.

Mixin de la classe TODO : ses méthodes vivent sur la même instance que celles
des autres fichiers, elles s'appellent donc par « self. » sans rien importer.
"""

import os
import shlex
import shutil

import click

from script.todo.todo_i18n import t

SYSFS_KSM = "/sys/kernel/mm/ksm"
TMPFILES_KSM = "/etc/tmpfiles.d/erplibre-ksm.conf"

# Valeurs de « run » : 0 arrête le démon et laisse partagé ce qui l'est déjà,
# 1 le lance, 2 l'arrête et défusionne toutes les pages.
RUN_ARRET = 0
RUN_ACTIF = 1
RUN_DEFUSION = 2

ACTIONS = ("activer", "desactiver", "permanent", "retirer")


def ligne_tmpfiles(sysfs=SYSFS_KSM):
    """La ligne qui réécrit « run » à chaque démarrage.

    systemd-tmpfiles applique « w » au démarrage, avant les services, et
    n'écrit que dans un fichier qui EXISTE : sur un noyau sans KSM la ligne
    ne fait rien, sans erreur. Mode, propriétaire, groupe et âge sont ignorés
    par « w », d'où les quatre « - ».
    """
    return f"w {sysfs}/run - - - - {RUN_ACTIF}"


def _lire_entier(chemin):
    with open(chemin, encoding="ascii") as fichier:
        return int(fichier.read().strip())


def lire_etat(sysfs=SYSFS_KSM, tmpfiles=TMPFILES_KSM, taille_page=None):
    """État de KSM, lu sans privilège.

    Rend un dict : « lisible », « raison », « run », « pages_sharing »,
    « mio », « permanent ». Quand « lisible » est faux, « raison » dit
    pourquoi et run, pages_sharing et mio valent None — « illisible » ne se
    confond jamais avec « inactif » :

    * « absent » : le répertoire sysfs manque, le noyau n'a pas KSM ;
    * « droits » : la lecture est refusée ;
    * « invalide » : un fichier ne porte pas un entier.

    « permanent » se lit à part, et vaut aussi quand sysfs est illisible.
    « mio » compte les pages partagées en Mio, avec la taille de page réelle
    du noyau, sauf si « taille_page » est donnée.
    """
    etat = {
        "lisible": False,
        "raison": "",
        "run": None,
        "pages_sharing": None,
        "mio": None,
        "permanent": os.path.exists(tmpfiles),
    }
    if not os.path.isdir(sysfs):
        etat["raison"] = "absent"
        return etat
    try:
        run = _lire_entier(os.path.join(sysfs, "run"))
        partage = _lire_entier(os.path.join(sysfs, "pages_sharing"))
    except FileNotFoundError:
        etat["raison"] = "absent"
        return etat
    except PermissionError:
        etat["raison"] = "droits"
        return etat
    except (OSError, ValueError):
        etat["raison"] = "invalide"
        return etat
    if taille_page is None:
        taille_page = os.sysconf("SC_PAGE_SIZE")
    etat.update(
        lisible=True,
        run=run,
        pages_sharing=partage,
        mio=partage * taille_page / (1024 * 1024),
    )
    return etat


def permanence_possible(which=shutil.which):
    """systemd-tmpfiles est-il là pour lire le fichier au démarrage ?

    Sans lui, le fichier ne serait lu par personne : la permanence se refuse
    plutôt que d'annoncer un réglage qui ne tiendra pas.
    """
    return which("systemd-tmpfiles") is not None


def commande(action, sysfs=SYSFS_KSM, tmpfiles=TMPFILES_KSM, sudo="sudo"):
    """La commande shell de « action », telle qu'elle sera montrée et lancée.

    « sudo » préfixe la seule commande qui écrit ; la chaîne vide la lance
    sous l'utilisateur courant, ce que font les tests sur des fichiers
    temporaires. Le code de retour d'un tube est celui de « tee », donc
    celui de sudo quand sudo refuse.
    """
    prefixe = f"{sudo} " if sudo else ""
    run = shlex.quote(os.path.join(sysfs, "run"))
    cible = shlex.quote(tmpfiles)
    if action == "activer":
        return f"echo {RUN_ACTIF} | {prefixe}tee {run} >/dev/null"
    if action == "desactiver":
        return f"echo {RUN_ARRET} | {prefixe}tee {run} >/dev/null"
    if action == "permanent":
        ligne = shlex.quote(ligne_tmpfiles(sysfs))
        return f"printf '%s\\n' {ligne} | {prefixe}tee {cible} >/dev/null"
    if action == "retirer":
        return f"{prefixe}rm -f {cible}"
    raise ValueError(action)


def atteint(action, etat):
    """L'état relu est-il celui que « action » vise ?"""
    if action == "activer":
        return etat["run"] == RUN_ACTIF
    if action == "desactiver":
        return etat["run"] == RUN_ARRET
    if action == "permanent":
        return etat["permanent"]
    if action == "retirer":
        return not etat["permanent"]
    raise ValueError(action)


def appliquer(
    action,
    executer,
    sysfs=SYSFS_KSM,
    tmpfiles=TMPFILES_KSM,
    sudo="sudo",
    taille_page=None,
):
    """Lance la commande de « action » par « executer », puis relit l'état.

    « executer » prend la commande shell et rend son code de retour. Rend
    (verdict, code, etat_relu) ; verdict vaut :

    * « fait » : l'état relu est celui visé ;
    * « refuse » : la commande a rendu un code non nul — sudo refusé ou
      écriture rejetée ;
    * « sans_effet » : code nul, mais l'état relu n'a pas bougé.
    """
    code = executer(commande(action, sysfs, tmpfiles, sudo))
    etat = lire_etat(sysfs, tmpfiles, taille_page)
    if code:
        return "refuse", code, etat
    if atteint(action, etat):
        return "fait", code, etat
    return "sans_effet", code, etat


class QemuKsmMixin:
    """Menu QEMU/KVM : KSM, le partage des pages identiques de la station."""

    # Surchargés par les tests, qui visent des fichiers temporaires.
    _KSM_SYSFS = SYSFS_KSM
    _KSM_TMPFILES = TMPFILES_KSM
    _KSM_SUDO = "sudo"

    def _qemu_ksm_state(self):
        return lire_etat(self._KSM_SYSFS, self._KSM_TMPFILES)

    def _qemu_ksm_show_state(self, etat):
        """Affiche l'état : marche, pages partagées, permanence."""
        print(f"\n🔗 {t('KSM - identical memory pages shared between VMs')}")
        if not etat["lisible"]:
            raison = {
                "absent": t("unreadable: this kernel has no KSM ({path})"),
                "droits": t("unreadable: permission denied on {path}"),
                "invalide": t("unreadable: unexpected content in {path}"),
            }[etat["raison"]]
            raison = raison.format(path=self._KSM_SYSFS)
            print(f"  {t('State:')} {raison}")
        else:
            libelle = {
                RUN_ACTIF: t("active"),
                RUN_ARRET: t("inactive"),
                RUN_DEFUSION: t("inactive, pages unmerged"),
            }.get(etat["run"], t("unknown"))
            print(f"  {t('State:')} {libelle} (run = {etat['run']})")
            partage = t("{pages} pages, {mio} MiB").format(
                pages=etat["pages_sharing"], mio=f"{etat['mio']:.0f}"
            )
            print(f"  {t('Shared:')} {partage}")
        if etat["permanent"]:
            permanent = t("yes ({path})").format(path=self._KSM_TMPFILES)
        else:
            permanent = t("no (lost at the next reboot)")
        print(f"  {t('Permanent:')} {permanent}")

    def _qemu_ksm_menu(self):
        """État de KSM, puis les quatre gestes qui le changent."""
        choices = [
            {"prompt_description": t("Enable KSM now")},
            {"prompt_description": t("Disable KSM now")},
            {"prompt_description": t("Make KSM permanent (every boot)")},
            {"prompt_description": t("Remove the KSM permanence")},
        ]
        help_info = self.fill_help_info(choices)
        while True:
            self._qemu_ksm_show_state(self._qemu_ksm_state())
            status = click.prompt(help_info)
            print()
            if status == "0":
                return False
            if status in ("1", "2", "3", "4"):
                self._qemu_ksm_action(ACTIONS[int(status) - 1])
            else:
                print(t("Command not found !"))

    def _qemu_ksm_action(self, action):
        """Montre la commande, la fait confirmer, la lance, dit le verdict."""
        etat = self._qemu_ksm_state()
        if action in ("activer", "desactiver") and etat["raison"] == "absent":
            print(f"✗ {t('Nothing to change: this kernel has no KSM.')}")
            return
        if action == "permanent" and not permanence_possible():
            print(f"✗ {t('systemd-tmpfiles is missing: no permanence here.')}")
            return
        cmd = commande(
            action, self._KSM_SYSFS, self._KSM_TMPFILES, self._KSM_SUDO
        )
        print(f"{t('Will execute:')} {cmd}")
        if not self._is_yes_default_yes(input(t("Run it now? (Y/n): "))):
            print(t("Cancelled."))
            return
        verdict, code, etat = appliquer(
            action,
            lambda c: self.execute.exec_command_live(c, source_erplibre=False),
            self._KSM_SYSFS,
            self._KSM_TMPFILES,
            self._KSM_SUDO,
        )
        if verdict == "fait":
            print(f"✓ {t('Done: the state read back is the expected one.')}")
            if action == "permanent" and etat["run"] != RUN_ACTIF:
                print(f"  {t('It applies from the next boot on.')}")
        elif verdict == "refuse":
            print(
                "✗ "
                + t(
                    "Refused (code {code}): sudo was denied or the write"
                    " was rejected."
                ).format(code=code)
            )
        else:
            print(f"✗ {t('Code 0, but the state read back is unchanged.')}")
