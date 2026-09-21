#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""L'écran des backends de VM : lequel est employé, et pourquoi celui-là.

La frontière avec `vm_backend_choice` est nette : ici on DEMANDE et on
affiche, là-bas on résout et on rend des lignes. Ce fichier ne sait ni la
règle d'« automatique », ni ce qui est éprouvé.

L'écran DIT que le choix est informatif. Sans cette phrase, choisir un
backend et voir le déploiement partir ailleurs se lit comme une panne, alors
que c'est ce qui est promis : la préférence préselectionne, elle ne route
rien tant qu'un seul chemin de déploiement existe.
"""

import shutil

from script.todo import host_os, todo_prefs, vm_backend_choice
from script.todo.todo_i18n import t

# La phrase qui évite de prendre une promesse tenue pour une panne.
NOTE_INDICATIVE = (
    "This choice informs and preselects; no deployment path drives another"
    " backend yet."
)


class VmBackendMenuMixin:
    """L'écran, greffé sur le menu Deploy."""

    def _deploy_vm_backends(self):
        """Montre les backends, et laisse en choisir un."""
        while True:
            pref = todo_prefs.get("vm_backend")
            jeton = host_os.host_os()
            # Sondé ICI, une fois par affichage, et passé en paramètre : le
            # module de résolution ne touche pas la machine, ce qui permet
            # de relire l'écran d'un autre système que le sien.
            limactl = bool(shutil.which("limactl"))
            print(f"\n🖥  {t('VM backends')}")
            print(f"  {t(NOTE_INDICATIVE)}\n")
            for ligne in vm_backend_choice.render(pref, jeton, limactl):
                print(ligne)
            print(f"\n  [0] {t('Back')}")
            reponse = input("> ").strip()
            if reponse == "0":
                return
            if reponse:
                self._deploy_backend_choose(reponse, jeton, limactl)

    @staticmethod
    def _deploy_backend_choose(reponse, jeton, limactl):
        """Retient le backend que ce numéro désigne, ou le dit."""
        from script.todo.todo import TODO

        _titre, options = TODO._PREF_CHOICES["vm_backend"]
        try:
            rang = int(reponse)
        except ValueError:
            print(t("Command not found !"))
            return
        if not 0 < rang <= len(options):
            print(t("Command not found !"))
            return
        valeur = options[rang - 1][0]
        todo_prefs.set("vm_backend", valeur)
        employe = vm_backend_choice.effective(valeur, jeton, limactl)
        print(f"  ✓ {t('In use:')} {employe}")
