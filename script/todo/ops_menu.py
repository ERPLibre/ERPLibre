#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Le menu Production : opérer une instance servie par systemd sur ce poste.

Ce mixin ne fait que poser les questions et lancer
`script/odoo/update_module.py`, qui porte toute la logique — détection,
arrêt, sauvegarde, mise à jour, relance. Le menu n'en duplique rien : ce
qui se fait depuis ici se fait aussi bien en ligne de commande.

La mise à jour passe toujours par deux temps :

1. la simulation (`--dry-run`), lancée sous le compte courant, montre ce
   qui a été détecté et les commandes exactes ;
2. après confirmation seulement, l'exécution réelle sous `sudo`, par
   `subprocess.run` SANS capture : le terminal reste celui du programme,
   ce qui permet à sudo de demander son mot de passe et au programme de
   poser sa question quand on l'interrompt par Ctrl-C.

Une simulation qui refuse (code non nul) arrête là : il n'y a rien à
confirmer.
"""

import os
import shlex
import subprocess
import sys

import click

from script.todo.todo_i18n import t

# Le programme lancé, relatif à la racine du dépôt (le dossier courant de
# todo.py).
UPDATE_MODULE = os.path.join("script", "odoo", "update_module.py")


class OpsMenuMixin:
    """Menu Production. Voir l'en-tête du fichier pour sa frontière."""

    def prompt_execute_production(self):
        print(
            f"🏭 {t('Production: an instance run by systemd on this host.')}"
        )
        choices = [
            {
                "prompt_description": t(
                    "Update modules - simulate, confirm, then run with sudo"
                )
            },
            {
                "prompt_description": t(
                    "Simulate only - show what an update would do"
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
                self._ops_update_modules()
            elif status == "2":
                self._ops_simulate_modules()
            else:
                print(t("Command not found !"))

    def _ops_update_arguments(self):
        """Les arguments d'update_module.py tirés des réponses, ou None.

        Modules exigés ; base vide = celle que le programme détecte ;
        sauvegarde par défaut. Les valeurs sont transmises telles quelles :
        update_module.py les valide et refuse avant d'arrêter quoi que ce
        soit.
        """
        modules = input(
            t("Modules to update (commas, * and ? patterns, or all): ")
        ).strip()
        if not modules:
            print(t("Cancelled: no module given."))
            return None
        base = input(t("Database (empty = detect from the service): ")).strip()
        sauvegarde = self._is_yes_default_yes(
            input(t("Back up the database before the update? [Y/n] "))
        )
        args = ["--module", modules]
        if base:
            args += ["--db", base]
        if not sauvegarde:
            args.append("--no-backup")
        return args

    def _ops_simulate_modules(self):
        """La simulation seule : jamais d'exécution réelle ni de sudo.

        Méthode distincte de `_ops_update_modules` pour que la table des
        méta-tests distingue les deux entrées par leur nom.
        """
        self._ops_update_modules(simulation_seule=True)

    def _ops_update_modules(self, simulation_seule=False):
        """Simulation, puis, sur confirmation, exécution réelle sous sudo."""
        args = self._ops_update_arguments()
        if args is None:
            return
        commande = [sys.executable, UPDATE_MODULE] + args
        simulation = " ".join(shlex.quote(a) for a in commande + ["--dry-run"])
        print(f"\n{t('Will execute:')} {simulation}")
        status = self.execute.exec_command_live(
            simulation, source_erplibre=False
        )
        if status != 0:
            print(f"  ✗ {t('The simulation refused: nothing was done.')}")
            return
        if simulation_seule:
            return
        if not click.confirm(
            t("Run this update for real? The service stops meanwhile.")
        ):
            return
        reelle = ["sudo"] + commande
        affichee = " ".join(shlex.quote(a) for a in reelle)
        print(f"\n{t('Will execute:')} {affichee}")
        fin = subprocess.run(reelle)
        if fin.returncode != 0:
            print(f"  ✗ {t('The update ended with code')} {fin.returncode}")
