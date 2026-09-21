#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""L'écran du carnet d'adresses : qui a le droit d'être joint, et d'où.

La frontière avec `egress_book` est nette : ici on DEMANDE et on affiche,
là-bas on lit, on contrôle et on écrit. Ce fichier ne connaît ni le nom des
trois fichiers de configuration, ni la forme d'une entrée.

TROIS CHOSES QUE CET ÉCRAN DOIT DIRE.

D'OÙ VIENT CHAQUE ADRESSE. La fusion ÉTEND les listes : un rôle présent
dans le carnet de l'équipe et dans celui de la machine porte les deux. Un
écran qui les additionne sans le dire laisse croire qu'il peut toutes les
retirer.

CE QU'UNE SUPPRESSION NE RETIRERA PAS. Elle ne touche que le carnet de
cette machine. Promettre plus laisserait croire une adresse fermée alors
qu'elle reste ouverte.

CE QUI MANQUE ENCORE À CHAQUE PROFIL. « VM paranoid » nomme sept rôles et
le déploiement refuse tant que l'un d'eux n'a pas d'adresse. Le lire ici
coûte un coup d'œil ; le découvrir après un formulaire entier coûte le
formulaire.
"""

import click

from script.lib_valid import ValidationError
from script.posture import allowlist
from script.todo import egress_book, vm_profiles
from script.todo.todo_i18n import t


def role_line(role: str, networks, shared) -> str:
    """Une ligne de carnet : le rôle, ses adresses, ce qui est indéracinable.

    Les adresses partagées sont marquées PLUTÔT que séparées : lues à part,
    elles se liraient comme un autre rôle, alors que la liste blanche les
    additionne dans la même règle.
    """
    partagees = set(shared or ())
    morceaux = []
    for reseau in networks or ():
        marque = " *" if reseau in partagees else ""
        morceaux.append(f"{reseau}{marque}")
    return f"{role} : {', '.join(morceaux) or t('no address')}"


def role_hint(role: str) -> str:
    """Ce que ce rôle sert, et sur quels ports. Vide s'il est inconnu.

    La raison vient du symbole et n'est pas recopiée : c'est elle qui dit
    POURQUOI une machine bornée en a besoin, et une copie divergerait.
    """
    symbole = allowlist.get(role)
    if symbole is None:
        return ""
    ports = ", ".join(str(p) for p in symbole.ports)
    return f"{symbole.reason} ({t('ports')} {ports})"


class EgressBookMenuMixin:
    def prompt_execute_egress_book(self):
        print(f"📓 {t('Site address book: what a confined VM may reach')}")
        try:
            egress_book.refuse_tracked()
        except ValidationError as refus:
            # NOMMÉ AVANT TOUT LE RESTE : une adresse dans le fichier suivi
            # part vers le dépôt public, et c'est la seule chose de cet
            # écran qui soit une faute et non un réglage.
            print(f"  ✗ {refus}")
            return False
        choices = [
            {"prompt_description": t("Book - Show the book")},
            {"prompt_description": t("Book - Set a role's addresses")},
            {"prompt_description": t("Book - Forget a role")},
            {"prompt_description": t("Book - What each profile still needs")},
        ]
        help_info = self.fill_help_info(choices)

        while True:
            status = click.prompt(help_info)
            print()
            if status == "0":
                return False
            elif status == "1":
                self._book_show()
            elif status == "2":
                self._book_set()
            elif status == "3":
                self._book_forget()
            elif status == "4":
                self._book_missing()
            else:
                print(t("Command not found !"))

    # ------------------------------------------------------------------
    # Voir
    # ------------------------------------------------------------------
    def _book_show(self):
        carnet = egress_book.read(self.config_file)
        if not carnet:
            print(f"  {t('The book is empty.')}")
            print(f"  {t('A confined profile refuses to deploy without it.')}")
            return
        partage = False
        for role in sorted(carnet):
            ailleurs = egress_book.shared_networks(role)
            partage = partage or bool(ailleurs)
            print(
                "  "
                + role_line(role, egress_book._reseaux(carnet[role]), ailleurs)
            )
        if partage:
            print(
                f"  * {t('comes from the team book: forgetting here '
                          'will not remove it')}"
            )

    # ------------------------------------------------------------------
    # Poser
    # ------------------------------------------------------------------
    def _book_set(self):
        role = self._book_pick_role()
        if not role:
            return
        self._book_write_role(role)

    def _book_write_role(self, role: str) -> bool:
        """Demande les adresses d'UN rôle et les écrit. Vrai si écrit.

        PARTAGÉ par « poser les adresses » et par « ce qui manque » : les
        deux écrans demandent la même chose, et une seconde copie aurait
        perdu l'indice, le refus à la saisie, ou les ports — c'est ce
        genre d'écart qui fait qu'un chemin refuse ce que l'autre accepte.
        """
        indice = role_hint(role)
        if indice:
            print(f"  {indice}")
        print(
            f"  {t('Networks, comma separated. An address alone means /32.')}"
        )
        print(
            f"  {t('A HOSTNAME is refused: resolving it would freeze the '
                    'address.')}"
        )
        saisie = input(f"{t('Networks: ')}").strip()
        if not saisie:
            print(t("Nothing typed: the book is unchanged."))
            return False
        reseaux = [m.strip() for m in saisie.split(",") if m.strip()]
        ports = self._book_ask_ports()
        try:
            egress_book.save(role, reseaux, ports, config=self.config_file)
        except ValidationError as refus:
            # REFUSÉ À LA SAISIE, et non au déploiement : une faute de
            # frappe se découvrait après un formulaire entier.
            print(f"  ✗ {refus}")
            return False
        print(f"  ✓ {t('Written for')} {role}")
        return True

    def _book_ask_ports(self):
        """Les ports du site pour ce rôle, ou () pour ceux du dépôt.

        Vide est le cas COURANT : le dépôt sait déjà sur quels ports un
        rôle se sert, et les recopier ici en figerait une version.
        """
        saisie = input(
            f"{t('Ports, comma separated (empty: the repository knows): ')}"
        ).strip()
        if not saisie:
            return ()
        valeurs = []
        for morceau in saisie.split(","):
            morceau = morceau.strip()
            if morceau.isdigit():
                valeurs.append(int(morceau))
        return tuple(valeurs)

    def _book_pick_role(self):
        """Un rôle du vocabulaire, "" si l'utilisateur renonce.

        Choisi dans une LISTE et non tapé : les rôles sont un vocabulaire
        clos, et un nom inventé serait refusé plus loin sans dire lequel
        était attendu.
        """
        noms = list(allowlist.symbol_names())
        for rang, nom in enumerate(noms, start=1):
            print(f"  [{rang}] {nom}")
        reponse = input(f"{t('Role number (empty to cancel): ')}").strip()
        if not reponse.isdigit() or not 1 <= int(reponse) <= len(noms):
            return ""
        return noms[int(reponse) - 1]

    # ------------------------------------------------------------------
    # Retirer
    # ------------------------------------------------------------------
    def _book_forget(self):
        role = self._book_pick_role()
        if not role:
            return
        ailleurs = egress_book.shared_networks(role)
        if ailleurs:
            # DIT AVANT LA CONFIRMATION : après, la question porterait sur
            # une suppression qu'on croit totale.
            print(
                f"  ⚠ {t('These addresses live in the team book and will '
                        'stay open:')} {', '.join(ailleurs)}"
            )
        if not self._is_yes(input(f"{t('Forget')} « {role} » ? [o/N] : ")):
            return
        if egress_book.forget(role, config=self.config_file):
            print(f"  ✓ {t('Forgotten from this machine:')} {role}")
        else:
            print(
                f"  {t('Not in this machine book, nothing changed:')} {role}"
            )

    # ------------------------------------------------------------------
    # Ce qui manque
    # ------------------------------------------------------------------
    def _book_missing(self):
        """Ce qui manque, puis de quoi le poser SANS quitter l'écran.

        Rendre la liste et s'arrêter là est un cul-de-sac : il faut
        retenir sept noms de rôle, revenir au menu, et les reposer un à
        un en retrouvant lequel servait à quoi.

        LA QUESTION EST « CE SITE A-T-IL CE SERVICE », pas « veux-tu le
        taper ». Un site qui n'a pas de coffre n'a pas d'adresse à
        donner, et la bonne réponse est non — l'écran dit alors ce qui
        reste bloqué, plutôt que de redemander.
        """
        bloques = self._book_report()
        if not bloques:
            return
        # UNE FOIS PAR RÔLE, et non par profil : un rôle posé débloque
        # d'un coup tous ceux qui l'attendaient, et le redemander ferait
        # retaper la même adresse.
        print()
        for role, profils in bloques.items():
            print(f"  · {role} — {t('unblocks:')} {', '.join(profils)}")
        if not self._is_yes(
            input(f"\n{t('Post the missing addresses now?')} [o/N] : ")
        ):
            return
        pose, refuses = 0, []
        for role in bloques:
            # LE RÔLE EST DANS LA QUESTION, et il n'y a pas d'en-tête
            # séparé : posé avant la réponse, il resterait orphelin à
            # l'écran quand on arrête, et se lirait comme un rôle traité.
            reponse = input(
                f"\n  {t('Does this site have a')} « {role} » ?"
                f" [o/N/{t('q to stop')}] : "
            ).strip()
            if reponse.lower() in ("q", "quit"):
                break
            if not self._is_yes(reponse):
                refuses.append(role)
                continue
            if self._book_write_role(role):
                pose += 1
        for role in refuses:
            # NOMMÉ, et non compté : « 3 rôles refusés » n'apprend pas
            # lesquels, et c'est ce qu'il faut pour savoir quoi déployer.
            # La phrase met le rôle en SUJET : « VM paranoid restent »
            # ne s'accorde pas quand un seul profil attend.
            print(
                f"  ○ {t('Left aside:')} {role} — "
                f"{t('still blocks:')} {', '.join(bloques[role])}"
            )
        if pose:
            print(f"\n{t('After posting:')}")
            self._book_report()

    def _book_report(self) -> dict:
        """Imprime l'état de chaque profil, et rend {rôle: [profils]}.

        Le dictionnaire est ce qui permet d'agir ensuite ; l'impression
        est ce qui permet de décider. Les deux au même endroit parce
        qu'une seconde lecture du carnet pourrait donner un autre état.
        """
        carnet = egress_book.read(self.config_file)
        bloques: dict = {}
        for profil in vm_profiles.profiles():
            manque = vm_profiles.missing_addresses(profil.posture, carnet)
            if manque:
                print(
                    f"  ✗ {profil.label} : {t('refuses to deploy, missing')}"
                    f" {', '.join(manque)}"
                )
                for role in manque:
                    bloques.setdefault(role, []).append(profil.label)
            else:
                print(f"  ✓ {profil.label}")
        return bloques
