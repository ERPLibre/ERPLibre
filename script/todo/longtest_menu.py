#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Les tests LONGS : de vraies machines, des heures.

Ils vivent dans `long_test/` et non dans `test/`, et ce n'est pas un rangement
de confort : le lanceur unitaire balaie `test/test_*.py` et doit rester
lançable en quelques secondes, partout. Un test qui crée dix VM n'a rien à y
faire — il le ferait échouer sur toute machine sans virtualisation, et
personne ne l'attendrait.

Ce menu ne fait que les lancer, en montrant leur sortie en direct : ces
scripts durent des heures, et une sortie capturée jusqu'à la fin ne dirait
rien pendant tout ce temps.
"""

import os

import click

from script.todo.menus import proxmox as menus_proxmox
from script.todo.todo_i18n import t
from script.todo.ui.navigator import navigate

# Les tests longs qui CRÉENT quelque chose, donc qui savent le défaire.
#
# Seconde copie de `long_test/descente.py::SCRIPTS`, et elle l'est faute de
# mieux : ce module-ci vit dans script/todo/ et lance les tests longs en
# sous-processus, sans jamais importer long_test/ — qui traîne avec lui le
# module Proxmox. Là-bas la liste sert au VERROU, ici au défaire.
SCRIPTS_DEFAISABLES = (
    "deep_proxmox.py",
    "deep_qemu.py",
    "qemu_cache.py",
    "install_nixos.py",
)

# Le répertoire des tests longs, à la racine du dépôt.
LONGTEST_DIR = "long_test"


class LongTestMenuMixin:
    def _longtest_script(self, nom):
        """Chemin d'un test long, ou "" s'il n'est pas là."""
        chemin = os.path.join(os.getcwd(), LONGTEST_DIR, nom)
        return chemin if os.path.exists(chemin) else ""

    # Ce qui ne crée aucune machine : un plan, un rapport, une liste. Ces
    # commandes-là ne méritent pas de question — une invite qu'on apprend à
    # confirmer sans lire ne protège plus rien le jour où elle compte.
    _LONGTEST_SANS_EFFET = ("--dry-run", "--rapport")

    @staticmethod
    def _longtest_question(args):
        """L'avertissement et la question qui vont avec ces arguments.

        Rend un couple de CLÉS de traduction, jamais du texte : l'invite est
        bilingue comme le reste du menu.
        """
        if "--detruire" in (args or ""):
            return (
                "This destroys the machines of this test and their disks.",
                "Destroy the machines of this test?",
            )
        return (
            "This creates real VMs and takes a while.",
            "Run this long test?",
        )

    def _longtest_run(self, nom, args="", demander=None):
        """Lance un test long, sortie en DIRECT.

        En direct parce qu'il dure des heures : capturer sa sortie pour
        l'afficher à la fin, c'est ne rien montrer pendant tout ce temps —
        et c'est justement la progression étage par étage qui intéresse.

        `demander` : None laisse la commande décider — on confirme dès qu'elle
        peut créer de vraies machines. Un appelant qui a DÉJÀ posé sa question
        passe False, sans quoi l'opérateur répondrait deux fois à la même.
        """
        chemin = self._longtest_script(nom)
        if not chemin:
            print(f"  ✗ {t('Script not found:')} {LONGTEST_DIR}/{nom}")
            return
        cmd = f"./.venv.erplibre/bin/python {chemin}"
        if args:
            cmd += f" {args}"
        print(f"\n{t('Will execute:')} {cmd}")
        if demander is None:
            demander = not any(
                d in (args or "") for d in self._LONGTEST_SANS_EFFET
            )
        if demander:
            # Une frappe ne doit suffire ni à créer de vraies machines, ni à
            # en effacer. La question doit dire LAQUELLE des deux on fait :
            # confirmer « lancer ce test long » devant une destruction fait
            # répondre oui à autre chose que ce qui va arriver.
            avertissement, question = self._longtest_question(args)
            print(f"  {t(avertissement)}")
            if not click.confirm(t(question)):
                return
        self.execute.exec_command_live(cmd, source_erplibre=False)

    def prompt_execute_longtest(self):
        """Les tests longs (LONGTEST, `menus/proxmox.py`) : deux descentes
        imbriquées, le cache de téléchargement, ERPLibre sur NixOS, chacun
        à blanc puis pour de vrai, et le défaire. Dessiné une fois, à
        l'entrée. Rend False sur [0]."""
        return navigate(self, menus_proxmox.LONGTEST)

    def _longtest_descente(self, script, dry_run=False):
        """Lance la descente `script`, deep_proxmox.py ou deep_qemu.py : la
        profondeur est DEMANDÉE, c'est le réglage qui décide de la durée —
        au-delà de trois étages, tout est 15 à 30 fois plus lent, et cinq
        se comptent en heures —, puis d'où elle part. `dry_run` n'en montre
        que le plan."""
        args = f"--depth {self._longtest_depth()}"
        args += self._longtest_depart(script)
        if dry_run:
            args += " --dry-run"
        self._longtest_run(script, args)

    def _longtest_nixos(self, dry_run=False):
        """Lance l'installation d'ERPLibre sur NixOS : pas de profondeur, une
        seule machine, et la question est binaire — l'installation aboutit
        ou non ; seul se demande d'où elle part. `dry_run` n'en montre que
        le plan."""
        args = self._longtest_depart_nixos()
        if dry_run:
            args += " --dry-run"
        self._longtest_run("install_nixos.py", args)

    def _longtest_defaire(self):
        """Défaire, chaque pile la sienne.

        Les deux scripts partagent le dossier des rapports mais chacun ne
        connaît que les siens : lancer les deux ne peut pas faire détruire à
        l'un ce que l'autre a créé.

        Le script demande « OUI » avant de détruire, mais il LISTE d'abord :
        on lui fait faire cette liste à blanc pour qu'un choix d'une touche ne
        mène pas directement à un « qm destroy --purge ».
        """
        for script in SCRIPTS_DEFAISABLES:
            self._longtest_run(script, "--detruire --dry-run", demander=False)
            if self._is_yes(input(f"\n{t('Destroy all that? (y/N): ')}")):
                self._longtest_run(script, "--detruire", demander=False)

    def _longtest_depart_nixos(self):
        """D'où part l'installation : une VM neuve, ou une machine NixOS
        qu'on possède déjà.

        La question n'est pas celle des descentes — il n'y a pas d'étage ici,
        et un hôte fourni doit DÉJÀ porter NixOS : le script y installe
        ERPLibre, il n'y installe pas le système.
        """
        print(f"\n{t('Where does the install run?')}")
        print(f"  [1] {t('Create a fresh NixOS VM')} *")
        print(f"  [2] {t('Use a NixOS machine you already have')}")
        if input(t("Choice (1-2, default 1): ")).strip() != "2":
            return ""
        hote = self._longtest_hote_manuel()
        if hote:
            return self._longtest_args_hote(hote)
        print(t("Cancelled."))
        return ""

    def _longtest_depart(self, script):
        """D'où part la descente : une VM neuve, ou un hôte qu'on a déjà.

        Créer une machine de tête pour héberger un hyperviseur qu'on possède
        déjà coûte cinq minutes ET un étage d'imbrication — donc de la
        lenteur, puisque c'est justement elle qu'on mesure.

        L'hôte déjà retenu est proposé sans qu'on ait à le rechercher : c'est
        `_pve_host(ask=False)`, qui ne demande rien et ne dit rien s'il n'y en
        a pas.
        """
        connu = None
        if script == "deep_proxmox.py":
            try:
                connu = self._pve_host(ask=False)
            except Exception:  # noqa: BLE001 - une préférence illisible
                connu = None
        print(f"\n{t('Where does the descent start?')}")
        print(f"  [1] {t('Create a fresh QEMU VM as level one')} *")
        if connu:
            print(f"  [2] {t('Start from:')} {self._pve_label(connu)}")
        print(f"  [3] {t('Start from another existing host')}")
        choix = input(t("Choice (1-3, default 1): ")).strip()
        if choix == "2" and connu:
            return self._longtest_args_hote(connu)
        if choix == "3":
            hote = (
                self._pve_pick_host()
                if script == "deep_proxmox.py"
                else self._longtest_hote_manuel()
            )
            if hote:
                return self._longtest_args_hote(hote)
            print(t("Cancelled."))
        return ""

    @staticmethod
    def _longtest_args_hote(hote):
        """Les options que le script attend, à partir d'un dict d'hôte."""
        args = f" --hote {hote['target']}"
        if hote.get("jump"):
            args += f" --jump {hote['jump']}"
        return args

    def _longtest_hote_manuel(self):
        """Un hôte libvirt de départ, saisi à la main.

        Pas de sélecteur vérifié comme pour Proxmox : ce qu'on veut ici, c'est
        un hôte qui porte KVM, et c'est le script qui le CONSTATE au premier
        contrôle — /dev/kvm et l'imbrication — plutôt que le menu qui le
        suppose.
        """
        cible = input(t("Address (user@host, blank = cancel): ")).strip()
        if not cible:
            return None
        return {
            "target": cible,
            "jump": input(t("SSH jump host (blank = none): ")).strip(),
        }

    def _longtest_depth(self):
        """Profondeur demandée. Trois par défaut, parce que trois marche.

        Trois étages se montent en une demi-heure ; au quatrième, chaque
        étape devient quinze à trente fois plus lente, et les suivants se
        comptent en jours (long_test/README.md). Un défaut plus profond
        promettrait ce qu'aucune machine ne tient.

        Des chiffres ASCII seulement : isdigit() accepte aussi « ² » ou un
        chiffre d'une autre écriture, sur lesquels int() lève ou lit un
        nombre que l'invite n'a pas montré. Trois chiffres au plus : int()
        lève au-delà de 4 300 chiffres (limite de conversion de Python), et
        une réponse plus longue garde le défaut comme tout autre texte.
        """
        brut = input(f"{t('Depth (default 3): ')}").strip()
        chiffres = brut.isascii() and brut.isdigit() and len(brut) <= 3
        return int(brut) if chiffres and int(brut) > 0 else 3
