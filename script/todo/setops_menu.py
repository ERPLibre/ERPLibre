#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Le menu Set-OPS : todo pilote le moteur, il ne le recopie pas.

Le moteur Set-OPS reste la seule source de vérité de ses gestes : un geste
s'ajoute ici en LANÇANT le moteur, jamais en recopiant ce qu'il fait. Le
menu n'affiche que ce qui existe — l'écran d'état de l'intégration, en
lecture seule ; les familles de gestes s'y ajoutent par sections.

Ses entrées se déclarent par « method » et non par un numéro : c'est la
forme dont le rang ne dépend pas de ce qui est posé plus haut.
"""

from __future__ import annotations

import os
import shlex

import click

from script.setops import ansible_env, ecosystems, engine, runner, state
from script.todo import state_screen
from script.todo.todo_i18n import t

# La racine d'ERPLibre, deux niveaux au-dessus de ce fichier : c'est sous
# elle que le relevé lit le manifeste du moteur et le chemin qu'il déclare.
RACINE = os.path.normpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")
)


class SetopsMenuMixin:
    """Menu Set-OPS, mixin de la classe TODO : ses entrées vivent sur la
    même instance que celles des autres menus."""

    def prompt_execute_setops(self):
        """Le menu Set-OPS. Rend False pour rester dans le menu appelant."""
        choices = [
            {"section": t("Integration")},
            {
                "prompt_description": t(
                    "Set-OPS - State of the integration, line by line"
                ),
                "method": "_setops_state",
            },
            {
                "prompt_description": t(state.GESTE_ANSIBLE),
                "method": "_setops_ansible_env",
            },
            {"section": t("Ecosystems")},
            {
                "prompt_description": t(
                    "Set-OPS - Ecosystems discovered beside the engine"
                ),
                "method": "_setops_ecosystems",
            },
            {
                "prompt_description": t(
                    "Set-OPS - Switch the active ecosystem"
                ),
                "method": "_setops_ecosystem_use",
            },
            {
                "prompt_description": t(
                    "Set-OPS - Create an ecosystem from a template"
                ),
                "method": "_setops_ecosystem_create",
            },
        ]
        help_info = self.fill_help_info(choices)

        while True:
            status = click.prompt(help_info)
            print()
            if status == "0":
                return False
            elif not self._menu_dispatch_extra(choices, status):
                print(t("Command not found !"))

    def _setops_state(self):
        """Les dix lignes de l'intégration de Set-OPS sur ce poste.

        LECTURE SEULE : le relevé de `script.setops.state` ne lance ni
        `make`, ni réseau, et n'écrit rien. Les lignes se décident sur ce
        relevé et s'impriment par le rendu commun des écrans d'état ; chaque
        ligne « à régler ici » nomme le geste qui la règle, et l'écran ne le
        lance pas.
        """
        print(f"\n{t('Set-OPS integration, line by line')}")
        vu = state.releve(RACINE)
        for ligne in state_screen.render(state.lignes(vu)):
            print(ligne)
        print(
            "\n  "
            + t(
                "Each « to set up here » line names the gesture that"
                " settles it; this screen launches nothing."
            )
        )

    def _setops_ansible_env(self):
        """Pose le venv Ansible du contrôleur, ou refait celui qui a dérivé.

        NE LANCE RIEN SANS L'AVOIR MONTRÉ : les commandes s'affichent telles
        qu'elles partiront, la question vient après. Chaque verdict est LU et
        une étape qui échoue arrête la suite — les suivantes bâtiraient sur
        un venv absent et n'échoueraient qu'à la fin, sur un message qui ne
        nomme plus la cause.
        """
        print(f"\n🤖 {t('Set-OPS - Ansible environment (set it up)')}")
        moteur = self._setops_moteur()
        if not moteur:
            return
        self._setops_bandeau(moteur)
        plage = ansible_env.plage_ansible(moteur)
        if ansible_env.specifieur(plage) is None:
            refus = t("the engine's ansible-core range is unreadable")
            print(f"  ✗ {refus}")
            return

        venv = ansible_env.chemin_venv(RACINE)
        posee = (
            ansible_env.version_posee(RACINE, ansible_env.PAQUET_ANSIBLE)
            if os.path.isdir(venv)
            else None
        )
        conforme = ansible_env.dans_la_plage(posee, plage) is True
        print(f"  {t('Engine')}: {os.path.relpath(moteur, RACINE)}")
        print(f"  {t('Range')}: {plage}")
        if conforme:
            print(
                f"  {t('Already installed')}: "
                f"{ansible_env.PAQUET_ANSIBLE} {posee}"
            )
            print(f"  {t('Nothing to do; the state screen says the rest.')}")
            return

        python, provenance = ansible_env.interprete()
        if python is None:
            self._setops_dire_python_manquant()
            return
        print(f"  {t('Interpreter')}: {python} ({provenance})")

        refaire = os.path.isdir(venv)
        if refaire:
            print(
                f"  {t('Found')}: {ansible_env.VENV}, "
                + (
                    t("ansible-core {version}").format(version=posee)
                    if posee
                    else t("no readable ansible-core")
                )
            )
        pas = ansible_env.etapes(RACINE, moteur, python, plage, refaire)
        print(f"\n  {t('What will run:')}")
        for rang, etape in enumerate(pas, 1):
            print(f"    {rang}. {ansible_env.montre(etape)}")
        if not self._is_yes(input(f"\n{t('Set it up? (y/N): ')}")):
            print(t("Cancelled."))
            return

        for rang, etape in enumerate(pas, 1):
            print(f"\n▶ {rang}/{len(pas)} {ansible_env.montre(etape)}")
            code = ansible_env.poser(etape, RACINE)
            if code:
                echec = t("step {n} failed (code {code}); stopping").format(
                    n=rang, code=code
                )
                print(f"  ✗ {echec}")
                return
        self._setops_verifier_ansible(moteur, plage)

    def _setops_dire_python_manquant(self):
        """Nomme l'interpréteur qui manque, et la commande qui le pose.

        Le menu ne pose pas un gestionnaire de versions de lui-même : il
        montre le geste, l'opérateur décide.
        """
        mineur = ansible_env.MINEUR_CIBLE
        manque = t("no python{minor} on this station").format(minor=mineur)
        print(f"  ✗ {manque}")
        geste = ansible_env.geste_mise()
        if geste is None:
            faute = t("install python{minor}, or mise, then come back")
            print(f"    {faute.format(minor=mineur)}")
        else:
            print(f"    {shlex.join(geste)}")

    def _setops_verifier_ansible(self, moteur, plage):
        """Les quatre constats d'après la pose, dans l'ordre où ils cassent.

        La vérification MESURE `python3` résolu par le PATH du geste, et non
        l'interpréteur du venv appelé par chemin : c'est ce que fera la garde
        du moteur, qui lance `python3` nu.
        """
        print(f"\n  {t('Verification:')}")
        posee = ansible_env.version_posee(RACINE, ansible_env.PAQUET_ANSIBLE)
        self._setops_constat(
            ansible_env.dans_la_plage(posee, plage) is True,
            f"{ansible_env.PAQUET_ANSIBLE} {posee or t('unreadable')}"
            f" / {plage}",
        )
        mineur = ansible_env.mineur_du_path(RACINE, moteur)
        self._setops_constat(
            mineur == ansible_env.MINEUR_CIBLE,
            t("python3 on the gesture PATH: {lu} (target {cible})").format(
                lu=mineur or t("unreadable"), cible=ansible_env.MINEUR_CIBLE
            ),
        )
        for nom, epinglee in ansible_env.bibliotheques_epinglees(moteur):
            vue = ansible_env.version_posee(RACINE, nom)
            self._setops_constat(
                vue == epinglee, f"{nom} {vue or t('absent')} / {epinglee}"
            )
        for nom, epinglee in ansible_env.collections_epinglees(moteur):
            vue = ansible_env.version_collection(moteur, nom)
            self._setops_constat(
                vue == epinglee, f"{nom} {vue or t('absent')} / {epinglee}"
            )

    @staticmethod
    def _setops_constat(ok, texte):
        print(f"    {'✓' if ok else '✗'} {texte}")

    # --- Écosystèmes -------------------------------------------------------

    def _setops_moteur(self):
        """Le chemin du moteur, ou « » après avoir dit qu'il manque.

        Chaque écran qui pilote le moteur commence par là : sans lui, la
        commande partirait vers un dossier absent et rendrait une erreur de
        `make` que personne ne sait lire.
        """
        decl = engine.declaration(RACINE)
        chemin = (
            os.path.join(RACINE, decl.path)
            if decl is not None and decl.path
            else ""
        )
        if not chemin or not os.path.isdir(chemin):
            manque = t("the engine is not here yet; see the state screen")
            print(f"  ✗ {manque}")
            return ""
        return chemin

    def _setops_bandeau(self, moteur):
        """L'écosystème actif, en tête de chaque écran qui agit.

        Lu sur le lien, sans lancer personne : un bandeau qui coûterait un
        sous-processus par écran se ferait retirer au premier ralentissement,
        et c'est justement celui qu'on ne doit pas perdre — tous les gestes
        du moteur portent sur l'écosystème monté.
        """
        nom = ecosystems.monte(moteur)
        print(f"  {t('Active ecosystem')}: {nom or t('none mounted')}")

    def _setops_lancer(
        self, moteur, cible, variables=(), confirmer=False, capture=True
    ):
        """Montre la commande, la joue, rend son `Verdict`.

        L'affichage vient AVANT le lancement : ce qui est montré est ce qui
        part, et la ligne se rejoue à la main sans todo.

        LE CHEMIN DU MOTEUR EST RELATIF À LA RACINE, et le geste part AVEC
        cette racine pour dossier courant. Un chemin absolu allongerait la
        ligne d'un chemin de compte et ne se recopierait pas d'un poste à
        l'autre ; relatif sans fixer le dossier, il dépendrait d'où todo a
        été lancé.
        """
        argv = runner.cible(
            os.path.relpath(moteur, RACINE), cible, variables, confirmer
        )
        print(f"\n▶ {runner.cite(argv)}")
        return runner.jouer(
            argv,
            env=ansible_env.environnement(RACINE, moteur, runner.base()),
            cwd=RACINE,
            capture=capture,
        )

    def _setops_liste(self, moteur):
        """Les écosystèmes découverts, ou None en ayant dit pourquoi.

        Le tableau est lu MÊME sur un code non nul : le moteur rend 2 sur une
        collision d'index, et cacher alors la liste priverait l'opérateur de
        ce qui explique le refus.
        """
        vu = self._setops_lancer(moteur, "instances")
        lus = ecosystems.lit_instances(vu.sortie)
        if lus is None:
            illisible = t("unreadable answer; replay the line above by hand")
            print(f"  ✗ {illisible}")
            if vu.sortie.strip():
                for ligne in vu.sortie.splitlines():
                    print(f"    {ligne}")
            return None
        if not vu.reussi:
            refus = t("the engine refused (code {code}); its own words:")
            print(f"  ⚠ {refus.format(code=vu.code)}")
            for ligne in vu.sortie.splitlines():
                print(f"    {ligne}")
        return lus

    @staticmethod
    def _setops_montrer(ecosystemes):
        """Les écosystèmes, numérotés, le monté marqué."""
        for rang, vu in enumerate(ecosystemes, 1):
            marque = "*" if vu.actif else " "
            etat = (
                t("production")
                if vu.production
                else (t("not production") if vu.production is False else "?")
            )
            portee = t("federated") if vu.federe else t("local")
            print(
                f"  {marque} [{rang}] {vu.nom}  "
                f"index {vu.index}  VLAN {vu.vlans}  {portee}  {etat}"
            )

    def _setops_ecosystems(self):
        """Les écosystèmes que le moteur découvre à côté de lui."""
        moteur = self._setops_moteur()
        if not moteur:
            return
        print(f"\n🤖 {t('Set-OPS - Ecosystems discovered beside the engine')}")
        self._setops_bandeau(moteur)
        lus = self._setops_liste(moteur)
        if lus is None:
            return
        if not lus:
            print(f"  {t('no ecosystem beside the engine yet')}")
            return
        self._setops_montrer(lus)

    def _setops_ecosystem_use(self):
        """Bascule l'écosystème actif, sur un nom CHOISI dans la liste.

        Le nom se choisit par son numéro, jamais en le retapant : un nom
        retapé de travers désigne un dossier absent, et le moteur refuse
        alors sans qu'on sache si c'est la frappe ou l'écosystème qui manque.
        """
        moteur = self._setops_moteur()
        if not moteur:
            return
        print(f"\n🤖 {t('Set-OPS - Switch the active ecosystem')}")
        self._setops_bandeau(moteur)
        lus = self._setops_liste(moteur)
        if not lus:
            if lus is not None:
                print(f"  {t('no ecosystem beside the engine yet')}")
            return
        self._setops_montrer(lus)
        choisi = self._setops_choisir(lus)
        if choisi is None:
            print(t("Cancelled."))
            return
        vu = self._setops_lancer(
            moteur, "instance-utiliser", [("NOM", choisi.nom)], confirmer=True
        )
        self._setops_dire(vu)

    @staticmethod
    def _setops_choisir(ecosystemes):
        """L'écosystème dont le numéro est tapé, ou None."""
        brut = input(t("Which one? (number, empty to cancel): ")).strip()
        if not brut.isdigit():
            return None
        rang = int(brut)
        if not 0 < rang <= len(ecosystemes):
            return None
        return ecosystemes[rang - 1]

    @staticmethod
    def _setops_dire(verdict):
        """Le compte rendu d'un geste : son code EST lu, et sa sortie aussi."""
        for ligne in verdict.sortie.splitlines():
            print(f"    {ligne}")
        if verdict.reussi:
            print(f"  ✅ {t('Done.')}")
        elif verdict.code is None:
            print(f"  ✗ {t('the gesture could not run at all')}")
        else:
            print(
                f"  ✗ {t('the engine refused (code {code}).').format(code=verdict.code)}"
            )

    def _setops_ecosystem_create(self):
        """Crée un écosystème depuis un modèle du moteur.

        Les trois valeurs sont EXIGÉES avant de montrer la ligne : le moteur
        refuse sans elles, et un refus après coup donne l'impression que le
        geste a été tenté.
        """
        moteur = self._setops_moteur()
        if not moteur:
            return
        print(f"\n🤖 {t('Set-OPS - Create an ecosystem from a template')}")
        self._setops_bandeau(moteur)
        vu = self._setops_lancer(moteur, "instance-modeles")
        lu = ecosystems.lit_modeles(vu.sortie) if vu.reussi else None
        if lu is None:
            illisible = t("unreadable answer; replay the line above by hand")
            print(f"  ✗ {illisible}")
            return
        modeles, pris = lu
        if not modeles:
            print(f"  ✗ {t('the engine offers no template')}")
            return
        nom = input(t("Name of the new ecosystem: ")).strip()
        if not nom:
            print(t("Cancelled."))
            return
        modele = self._setops_choisir_modele(modeles)
        if modele is None:
            print(t("Cancelled."))
            return
        index = self._setops_choisir_index(pris)
        if index is None:
            print(t("Cancelled."))
            return
        vu = self._setops_lancer(
            moteur,
            "instance-creer",
            [("NOM", nom), ("MODELE", modele), ("INDEX", str(index))],
            confirmer=True,
        )
        self._setops_dire(vu)

    @staticmethod
    def _setops_choisir_modele(modeles):
        """Le modèle dont le numéro est tapé, ou None."""
        print(f"\n  {t('Templates the engine offers:')}")
        for rang, nom in enumerate(modeles, 1):
            print(f"    [{rang}] {nom}")
        brut = input(t("Which template? (number): ")).strip()
        if not brut.isdigit() or not 0 < int(brut) <= len(modeles):
            return None
        return modeles[int(brut) - 1]

    @staticmethod
    def _setops_choisir_index(pris):
        """L'index tapé, ou celui proposé si la réponse est vide, ou None.

        La proposition épargne de chercher un trou dans la liste ; le moteur
        valide lui-même ce qu'il reçoit et refuse une collision fédérée.
        """
        libre = ecosystems.index_libre(pris)
        deja = ", ".join(str(i) for i in sorted(pris)) or t("none")
        print(f"\n  {t('Federated indexes already taken')}: {deja}")
        if libre is None:
            print(f"  ✗ {t('no free index left in range')}")
            return None
        question = t("Index? (empty for {free}): ").format(free=libre)
        brut = input(question).strip()
        if not brut:
            return libre
        return int(brut) if brut.isdigit() else None
