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
import signal
import time

import click

from script.setops import (
    ansible_env,
    console,
    ecosystems,
    engine,
    runner,
    state,
    vaults,
)
from script.setops import runbooks as registre
from script.todo import state_screen
from script.todo.todo_i18n import t

# La racine d'ERPLibre, deux niveaux au-dessus de ce fichier : c'est sous
# elle que le relevé lit le manifeste du moteur et le chemin qu'il déclare.
RACINE = os.path.normpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")
)


def saisir(invite=""):
    """Une réponse de l'opérateur, « » s'il coupe la saisie.

    AUCUNE SAISIE DE CES ÉCRANS N'EST NUE. Un Ctrl-D lève `EOFError`, que le
    rattrapage de tête de todo ne couvre pas — il ne prend que
    `KeyboardInterrupt` et `click.Abort` — et todo mourait sur une trace de
    pile. Les autres menus le rattrapent ; ceux-ci ne le faisaient pas.

    Une réponse vide vaut refus partout où elle est lue : couper la saisie ne
    lance donc rien, et n'en confirme rien.

    Fonction du MODULE et non méthode : plusieurs écrans de ce mixin sont
    statiques et n'ont pas de `self` sous la main.
    """
    try:
        return input(invite)
    except (EOFError, KeyboardInterrupt):
        print()
        return ""


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
            {
                "prompt_description": t(engine.GESTE_EPINGLE),
                "method": "_setops_epingle",
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
            {"section": t("Keys and vaults")},
            {
                "prompt_description": t(state.GESTE_VOUTES),
                "method": "_setops_vaults",
            },
            {"section": t("Runbooks")},
            {
                "prompt_description": t(
                    "Set-OPS - Runbooks (the engine's sequences, in order)"
                ),
                "method": "_setops_runbooks",
            },
            {"section": t("Write gestures")},
            {
                "prompt_description": t(registre.PORTE_INSTANCIER),
                "method": "_setops_geste_instancier",
            },
            {
                "prompt_description": t(registre.PORTE_INSTANCIER_APPLIQUER),
                "method": "_setops_geste_instancier_appliquer",
            },
            {
                "prompt_description": t(registre.PORTE_DEPLOYER),
                "method": "_setops_geste_deployer",
            },
            {
                "prompt_description": t(registre.PORTE_DEPLOYER_GROUPE),
                "method": "_setops_geste_deployer_groupe",
            },
            {
                "prompt_description": t(registre.PORTE_APPLIQUER),
                "method": "_setops_geste_appliquer",
            },
            {
                "prompt_description": t(registre.PORTE_CREER_VM),
                "method": "_setops_geste_creer_vm",
            },
            {
                "prompt_description": t(registre.PORTE_FLOTTE_CREER),
                "method": "_setops_geste_flotte_creer",
            },
            {
                "prompt_description": t(registre.PORTE_FLUX),
                "method": "_setops_geste_flux",
            },
            {
                "prompt_description": t(registre.PORTE_SITE),
                "method": "_setops_geste_site",
            },
            {
                "prompt_description": t(registre.PORTE_GENOME_INSCRIRE),
                "method": "_setops_geste_genome_inscrire",
            },
            {
                "prompt_description": t(registre.PORTE_CONFIG),
                "method": "_setops_geste_config",
            },
            {"section": t("Web console")},
            {
                "prompt_description": t(console.GESTE),
                "method": "_setops_console",
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
        if not self._is_yes(saisir(f"\n{t('Set it up? (y/N): ')}")):
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
        brut = saisir(t("Which one? (number, empty to cancel): ")).strip()
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
        nom = saisir(t("Name of the new ecosystem: ")).strip()
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
        brut = saisir(t("Which template? (number): ")).strip()
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
        brut = saisir(question).strip()
        if not brut:
            return libre
        return int(brut) if brut.isdigit() else None

    # --- Runbooks ----------------------------------------------------------

    TITRE_RUNBOOKS = "Set-OPS - Runbooks (the engine's sequences, in order)"

    # Les marques de nature, celles que la console du moteur emploie déjà :
    # les relire ailleurs avec d'autres signes ferait deux vocabulaires.
    MARQUES_NATURE = {
        registre.MESURE: " ",
        registre.ECRITURE: "*",
        registre.DESTRUCTIF: "!",
    }

    # Ce qu'une barrière dit à l'écran. Le vocabulaire est clos dans la
    # couche ; l'écran ne fait que le traduire.
    BARRIERES = {
        registre.DESTRUCTIVE: "destructive: the engine keeps this one",
        registre.A_REMETTRE: (
            "type it yourself: it waits for an answer todo cannot give"
        ),
        registre.CONFIRMATION_MOTEUR: (
            "the engine demands its own confirmation"
        ),
        registre.SANS_ECOSYSTEME: "no ecosystem mounted",
        registre.SANS_SITE: "no site mounted",
        registre.FORME_INCONNUE: "unreadable step",
    }

    def _setops_registre(self, moteur):
        """Les runbooks du moteur, ou None après avoir dit pourquoi.

        Le registre est lu en LANÇANT le script du moteur, jamais en
        l'important : todo ne se lie pas aux noms internes du moteur.
        """
        argv = registre.ARGV_REGISTRE
        print(f"\n▶ {runner.cite(argv)}")
        vu = runner.jouer(
            argv,
            env=ansible_env.environnement(RACINE, moteur, runner.base()),
            cwd=moteur,
        )
        lu = registre.lit_registre(vu.sortie)
        if lu is None:
            print(
                "  ✗ " + t("unreadable answer; replay the line above by hand")
            )
            # LES MOTS DU MOTEUR, comme le font le relevé des voûtes et la
            # liste des écosystèmes. Jetés, une trace Python ou un refus motivé
            # devenait « réponse illisible » — et c'est la porte d'entrée de
            # l'écran des séquences ET des onze portes d'écriture.
            for ligne in vu.sortie.splitlines():
                print(f"    {ligne}")
        return lu

    def _setops_runbooks(self):
        """Les séquences du moteur, dans leur ordre. RIEN N'EST MASQUÉ.

        Une séquence dont on retirerait ce que todo ne lance pas mentirait
        par omission : huit des dix-sept en ont, et l'une commencerait à son
        étape 2. Chaque étape est donc là, et ce qui ne part pas d'ici porte
        sa raison — comme l'écran d'état montre ses dix lignes plutôt que la
        seule liste de ce qui est prêt.
        """
        moteur = self._setops_moteur()
        if not moteur:
            return
        print("\n🤖 " + t(self.TITRE_RUNBOOKS))
        self._setops_bandeau(moteur)
        lus = self._setops_registre(moteur)
        if lus is None:
            return
        ecosysteme, site = (
            ecosystems.monte(moteur),
            ecosystems.site_monte(moteur),
        )
        for rang, runbook in enumerate(lus, 1):
            ouvertes, total = registre.compte(runbook, ecosysteme, site)
            print(
                f"  [{rang}] {runbook.id:<22} [{runbook.portee}]"
                f"  {ouvertes}/{total}  {runbook.titre}"
            )
        print(
            "\n  "
            + t("{n} of {m} steps can be driven from here").format(
                n=sum(registre.compte(r, ecosysteme, site)[0] for r in lus),
                m=sum(len(r.etapes) for r in lus),
            )
        )
        choisi = self._setops_choisir_runbook(lus)
        if choisi is None:
            return
        self._setops_sequence(moteur, choisi, ecosysteme, site)

    @staticmethod
    def _setops_choisir_runbook(runbooks):
        """Le runbook dont le numéro est tapé, ou None."""
        brut = saisir(t("Which sequence? (number, empty to leave): ")).strip()
        if not brut.isdigit() or not 0 < int(brut) <= len(runbooks):
            return None
        return runbooks[int(brut) - 1]

    def _setops_sequence(self, moteur, runbook, ecosysteme, site):
        """Une séquence, entière, chaque étape marquée ; puis un geste."""
        print(f"\n  {runbook.titre}  [{runbook.portee}]")
        if runbook.but:
            print(f"    {runbook.but}")
        for rang, etape in enumerate(runbook.etapes, 1):
            self._setops_dire_etape(rang, etape, ecosysteme, site)
        etape = self._setops_choisir_etape(runbook, ecosysteme, site)
        if etape is None:
            return
        self._setops_jouer_etape(moteur, etape)

    def _setops_dire_etape(self, rang, etape, ecosysteme, site):
        """Une étape, sa nature, et ce qui l'empêche le cas échéant.

        LE PALIER EST JUGÉ COMME S'IL ÉTAIT CONFIRMÉ, ici et au choix : sa porte
        demandera la vraie confirmation, et le barrer à l'affichage le rendrait
        inatteignable. Ce qui reste barré l'est pour une IMPOSSIBILITÉ — pas de
        site monté, forme illisible — et non pour une précaution.
        """
        barriere = registre.barriere(
            etape, ecosysteme, site, confirme=registre.destructeur(etape)
        )
        marque = self.MARQUES_NATURE.get(etape.nature, "?")
        facultative = f"  ({t('optional')})" if etape.facultative else ""
        print(f"    {marque} [{rang}] make {etape.cible}{facultative}")
        if etape.libelle:
            print(f"        {etape.libelle}")
        if barriere:
            print(f"        ⛔ {t(self.BARRIERES[barriere])}")
        elif registre.destructeur(etape):
            print(f"        ⚠ {t('DESTRUCTIVE tier: a retype is demanded')}")

    def _setops_choisir_etape(self, runbook, ecosysteme, site):
        """L'étape dont le numéro est tapé, si elle se conduit d'ici.

        Une étape barrée refuse en NOMMANT sa barrière : taper son numéro
        est la question qu'on se pose en la voyant, et répondre « choix
        invalide » ferait croire à une faute de frappe.
        """
        brut = saisir(t("Which step? (number, empty to leave): ")).strip()
        if not brut.isdigit() or not 0 < int(brut) <= len(runbook.etapes):
            return None
        etape = runbook.etapes[int(brut) - 1]
        barriere = registre.barriere(
            etape, ecosysteme, site, confirme=registre.destructeur(etape)
        )
        if barriere:
            print(f"  ⛔ {t(self.BARRIERES[barriere])}")
            return None
        return etape

    def _setops_jouer_etape(self, moteur, etape):
        """Montre la ligne, demande s'il faut, lance, lit le verdict.

        TODO POSE SA PROPRE CONFIRMATION SUR UNE ÉCRITURE, même là où la
        cible ne lit pas `CONFIRMER`. La ligne affichée porte
        `CONFIRMER=false`, et pour ces cibles-là le drapeau ne veut rien
        dire : sans cette question, la ligne enseignerait qu'un « false »
        protège. L'écart avec le `make` à la main est dit à l'écran.
        """
        variables = []
        if etape.variables:
            print(f"\n  {t('This step takes variables:')}")
            for attendue in etape.variables:
                # L'INVITE VIENT DU MOTEUR, pas d'ici : la reformuler ferait
                # deux libellés pour la même question, et celui du moteur est
                # celui que sa propre console affiche déjà.
                suffixe = f" ({t('optional')})" if attendue.facultative else ""
                valeur = saisir(
                    f"    {attendue.nom}{suffixe} — {attendue.invite}\n"
                    f"    {attendue.nom}="
                ).strip()
                if not valeur:
                    if attendue.facultative:
                        # Une facultative laissée vide n'est pas passée : le
                        # moteur a son propre défaut, et « VAR= » le noierait.
                        continue
                    manque = t("{name} is required; nothing was run.")
                    print(f"  ⛔ {manque.format(name=attendue.nom)}")
                    return
                variables.append((attendue.nom, valeur))
        interrupteur = registre.drapeau(etape)
        if interrupteur and self._setops_demander_interrupteur(interrupteur):
            variables.append((interrupteur, "1"))
        if etape.pourquoi:
            print(f"\n  {etape.pourquoi}")
        if registre.destructeur(etape):
            self._setops_franchir_le_palier(moteur, etape, variables)
            return
        if registre.ecrit(etape):
            print(f"\n  ⚠ {t('This step WRITES.')}")
            print(
                f"    {t('The engine does not gate it, so TODO asks here.')}"
            )
            if not self._is_yes(saisir(f"{t('Run it? (y/N): ')}")):
                print(t("Cancelled."))
                return
        self._setops_dire(self._setops_lancer(moteur, etape.cible, variables))

    # CE QUE L'ÉCRAN DEMANDE DE RETAPER, un libellé par chose. Les trois disent
    # d'où vient la valeur, et non ce que le geste touchera : un geste de portée
    # poste ne touche pas forcément des hôtes — l'un d'eux ne fait que reposer
    # des clés — et promettre le contraire serait affirmer faux.
    RETAPES = {
        registre.RETAPE_ECOSYSTEME: "Retype the name of the MOUNTED ecosystem:",
        registre.RETAPE_SITE: "Retype the name of the MOUNTED site:",
        registre.RETAPE_HOTES: (
            "Retype the number of ACTIVE hosts the plan declares:"
        ),
    }

    def _setops_franchir_le_palier(self, moteur, etape, variables):
        """La porte d'un geste du PALIER : essai, retape, verrou, vrai appel.

        QUATRE GARDES EN FILE, et chacun répare une façon précise de se tromper.

        L'ESSAI D'ABORD. Le geste est lancé avec `CONFIRMER=false`, et ce que le
        moteur répond est MONTRÉ : il dit ce qu'il ferait, parfois en listant les
        machines. C'est la seule occasion de voir la portée réelle avant qu'elle
        soit appliquée, et elle ne coûte rien.

        LA RETAPE ENSUITE. Un oui-non se confirme de mémoire ; recopier un nom ou
        un nombre lu à l'écran oblige à REGARDER. Ce qu'on demande vient de la
        portée déclarée, et sa valeur d'une mesure — jamais d'une invite qui
        rappellerait la réponse.

        LE VERROU AVANT LE VRAI APPEL, et pas avant l'essai : deux essais en même
        temps ne se gênent pas, deux applications si.

        LE VERDICT SE LIT, code ET sortie. Plusieurs gestes du moteur rendent zéro
        en ayant trouvé un écart.
        """
        print(f"\n  ⚠ {t('This gesture is in the DESTRUCTIVE tier.')}")
        print(
            f"    {t('A trial runs first: the engine says what it would do.')}"
        )
        essai = self._setops_lancer(moteur, etape.cible, variables)
        self._setops_dire(essai)

        attendu = self._setops_attendu_du_palier(moteur, etape)
        if not attendu:
            print(f"\n  ⛔ {t('Nothing to ask for: it could not be read.')}")
            return
        quoi = registre.retape(etape)
        print()
        # L'ALERTE MONTRE LES DEUX NOMBRES, elle ne prétend pas détecter l'écart.
        # Le moteur rend la MÊME valeur pour « la flotte est vide » et pour « la
        # lecture d'API n'a rien dit » : son client rend une liste vide sur un
        # corps vide comme sur une erreur, si bien qu'un geste destructeur peut
        # annoncer « rien à faire » sans avoir lu quoi que ce soit — et annoncer
        # cela AVANT d'évaluer ses propres verrous. Todo ne peut donc pas
        # trancher à la place de l'opérateur ; il peut mettre côte à côte ce que
        # le PLAN déclare et ce que l'essai vient de dire, et nommer le piège.
        if quoi == registre.RETAPE_HOTES and attendu != "0":
            alerte = t(
                "The plan declares {n} active host(s). If the trial above saw"
                " none, the state may not have been READ: an empty API answer"
                " does not differ from an empty fleet."
            )
            print(f"  ⚠ {alerte.format(n=attendu)}")
            print()
        tape = saisir(f"  {t(self.RETAPES[quoi])} « {attendu} »\n  > ")
        if not registre.retape_concorde(attendu, tape):
            print(
                f"  ⛔ {t('What was typed does not match. Nothing was run.')}"
            )
            return

        with runner.verrou_du_moteur(moteur) as libre:
            if not libre:
                print(f"\n  ⛔ {t('Another gesture holds this engine lock.')}")
                return
            print(f"\n  {t('Now for real:')}")
            self._setops_dire(
                self._setops_lancer(
                    moteur, etape.cible, variables, confirmer=True
                )
            )

    def _setops_attendu_du_palier(self, moteur, etape):
        """La valeur à retaper pour ce geste, MESURÉE. Ou « ».

        « » ARRÊTE LE GESTE. Sans savoir ce qu'on demande, on ne peut pas
        comparer, et un garde qui accepte n'importe quoi parce qu'il n'attend
        rien est pire que pas de garde : il donne l'assurance d'en être un.

        LE COMPTE D'HÔTES VIENT D'UN GESTE DU REGISTRE, la liste des serveurs du
        plan, et non d'une commande bâtie ici. Une lecture qui n'aboutit pas ne
        devient PAS zéro : « aucun hôte actif » se confirme par « 0 », « on n'a
        pas su lire » ne se confirme pas du tout.
        """
        quoi = registre.retape(etape)
        if quoi == registre.RETAPE_ECOSYSTEME:
            return registre.attendu_retape(
                quoi, ecosysteme=ecosystems.monte(moteur)
            )
        if quoi == registre.RETAPE_SITE:
            return registre.attendu_retape(
                quoi, site=ecosystems.site_monte(moteur)
            )
        if quoi == registre.RETAPE_HOTES:
            vu = self._setops_lancer(moteur, registre.CIBLE_SERVEURS)
            if not vu.reussi:
                return ""
            return registre.attendu_retape(
                quoi,
                hotes=ecosystems.compte_actifs(
                    ecosystems.lit_serveurs(vu.sortie)
                ),
            )
        return ""

    def _setops_demander_interrupteur(self, nom):
        """Un drapeau-INTERRUPTEUR se demande par oui ou non, jamais par sa
        valeur.

        La recette le lit par `$(if $(NOM),…)`, et GNU make tient toute chaîne
        non vide pour vraie : celui qui tape « 0 » pour dire non force tout
        autant. La question est donc fermée, et « non » ne passe RIEN — pas
        même un « NOM= » vide, qui se lirait comme une valeur choisie.
        """
        print(
            f"\n  ⚠ {t('{name} is a switch, not a value:').format(name=nom)}"
        )
        print(f"    {t('any value at all turns it on, « 0 » included.')}")
        demande = t("Turn {name} on? (y/N): ").format(name=nom)
        return self._is_yes(saisir(demande))

    # --- Clés et voûtes -----------------------------------------------------

    # Ce qu'un état dit à l'écran. UNE ABSENCE VOULUE NE PORTE PAS LA MARQUE
    # D'UNE PANNE : sur le runner d'un locataire, la clé du site manque parce
    # qu'il ne doit pas pouvoir l'ouvrir, et la marquer comme un défaut
    # enverrait réparer une séparation qui tient.
    VOUTES = {
        vaults.PRESENTE: ("🔑", "this machine opens it"),
        vaults.ABSENTE_BLOQUANTE: (
            "⛔",
            "KEY MISSING — this machine configures nothing",
        ),
        vaults.SANS_CLE: ("🔒", "this machine does not open it, and must not"),
    }

    # Ce que rend la pose d'un fichier-clé. Le vocabulaire est clos dans la
    # couche ; l'écran ne fait que le traduire.
    POSES = {
        vaults.POSEE: "key posed, readable by you alone",
        vaults.DEJA_LA: (
            "a key is already there and was NOT replaced: replacing it"
            " would make that vault unreadable for good"
        ),
        vaults.SANS_CHEMIN: "the engine named no path for that key",
        vaults.ECHEC: "the file could not be written",
    }

    def _setops_voutes(self, moteur):
        """Les voûtes que le moteur nomme, ou None après avoir dit pourquoi.

        UN CODE 1 N'EST PAS UN ÉCHEC ICI : le moteur rend 1 quand la clé de
        l'instance montée manque, et c'est exactement le cas que cet écran
        existe pour montrer. C'est donc la LECTURE du tableau qui décide, pas
        le code — le gater sur un 0 cacherait le rapport au moment où il sert.
        """
        argv = vaults.ARGV_ETAT
        print(f"\n▶ {runner.cite(argv)}")
        vu = runner.jouer(
            argv,
            env=ansible_env.environnement(RACINE, moteur, runner.base()),
            cwd=moteur,
        )
        lues = vaults.lit_etat(vu.sortie)
        if lues is None:
            print(
                "  ✗ " + t("unreadable answer; replay the line above by hand")
            )
            for ligne in vu.sortie.splitlines():
                print(f"    {ligne}")
        return lues

    def _setops_vaults(self):
        """Ce que cette machine peut ouvrir, et ce qu'elle ne doit pas.

        Le rapport du moteur ne nomme que des CHEMINS : une clé absente du
        disque n'y figure pas comme valeur, et c'est la présence des fichiers
        qui borne le pouvoir. Aucune clé n'est lue, ni affichée, ni
        journalisée — ni par le moteur, ni par cet écran.
        """
        moteur = self._setops_moteur()
        if not moteur:
            return
        print("\n🤖 " + t(state.GESTE_VOUTES))
        self._setops_bandeau(moteur)
        lues = self._setops_voutes(moteur)
        if lues is None:
            return
        if not lues:
            print(
                "  "
                + t("nothing to name: no ecosystem mounted, and no underlay")
            )
            return
        for vue in lues:
            marque, dit = self.VOUTES[vue.etat]
            print(f"  {marque} {vue.role:<10} {vue.nom:<22} {t(dit)}")
            print(f"       {vue.chemin}")
        self._setops_dire_separation(lues)
        self._setops_dire_remises(moteur)
        self._setops_gestes_voutes(moteur, vaults.bloquante(lues))

    def _setops_dire_separation(self, voutes):
        """Ce que cette machine n'ouvre pas, dit comme un fait et non un manque.

        Sans cette phrase, deux lignes 🔒 se lisent comme deux choses à
        régler, et la réparation consisterait à donner à ce poste des clés
        qu'il ne doit pas détenir.
        """
        if not vaults.separation(voutes):
            return
        print(
            "\n  🔒 "
            + t(
                "A key missing above is not a fault: it is a separation that"
                " holds. Posing one here would open nothing — the secret of"
                " that vault already exists elsewhere."
            )
        )

    def _setops_dire_remises(self, moteur):
        """Les gestes que todo REMET, avec la ligne à taper soi-même.

        `gpg` demande une phrase de passe : elle va de la main au terminal
        sans traverser un outil qui pourrait la retenir. La ligne porte la
        variable que la cible exige, parce qu'une ligne remise sans elle se
        fait refuser et la remise n'aurait rien donné.
        """
        relatif = os.path.relpath(moteur, RACINE)
        print(
            "\n  "
            + t("Type these in your own terminal — they ask for a passphrase:")
        )
        for cible, variable in registre.remises().items():
            argument = f" {variable}=…" if variable else ""
            print(f"    make -C {relatif} {cible}{argument}")

    def _setops_gestes_voutes(self, moteur, bloque):
        """Les gestes de cet écran, numérotés ; le geste tapé part.

        La pose n'est proposée QUE pour la voûte bloquante : c'est la seule
        dont l'absence empêche cette machine de travailler, et la seule pour
        laquelle une clé neuve ait un sens.
        """
        gestes = ["poser"] if bloque is not None else []
        gestes.append("recenser")
        print()
        for rang, geste in enumerate(gestes, 1):
            if geste == "poser":
                pose = t("Pose a NEW key for {nom}")
                print(f"  [{rang}] {pose.format(nom=bloque.nom)}")
            else:
                print(
                    f"  [{rang}] make {vaults.CIBLE_RECENSER} — "
                    + t("what exists only on this station (writes nothing)")
                )
        brut = saisir(t("Which gesture? (number, empty to leave): ")).strip()
        if not brut.isdigit() or not 0 < int(brut) <= len(gestes):
            return
        if gestes[int(brut) - 1] == "poser":
            self._setops_poser_cle(bloque)
        else:
            self._setops_dire(
                self._setops_lancer(moteur, vaults.CIBLE_RECENSER)
            )

    def _setops_poser_cle(self, bloque):
        """Pose une clé neuve pour la voûte bloquante. NE L'AFFICHE JAMAIS.

        LA QUESTION DIT LES DEUX CAS, parce que ni la couche ni cet écran ne
        savent les distinguer : une clé neuve n'ouvre qu'une voûte qui ne
        porte encore rien. Sur une voûte déjà chiffrée, elle ne récupère rien
        — ce secret-là revient de son archive — et Ansible essaierait alors
        une clé qui n'ouvre aucun bloc.

        La pose n'écrase jamais un fichier existant : la couche refuse, parce
        qu'une clé remplacée rend sa voûte définitivement illisible.
        """
        print(
            "\n  ⚠ "
            + t(
                "A new key only opens a vault that holds nothing yet. If this"
                " ecosystem already has encrypted files, bring its key back"
                " from its archive instead."
            )
        )
        print(f"    {bloque.chemin}")
        demande = t("Pose a new key for {nom}? (y/N): ")
        if not self._is_yes(saisir(demande.format(nom=bloque.nom))):
            print(t("Cancelled."))
            return
        pose = vaults.poser_cle(bloque.chemin)
        dit = t(self.POSES[pose.resultat])
        if pose.reussi:
            print(f"  ✅ {dit}")
            return
        print(f"  ✗ {dit}" + (f" ({pose.souci})" if pose.souci else ""))

    # --- Console web --------------------------------------------------------

    # Ce qu'un état dit à l'écran. Le vocabulaire est clos dans la couche.
    CONSOLES = {
        console.ARRETEE: ("○", "not running here"),
        console.VIVANTE: ("●", "running, started from here"),
        console.MUETTE: (
            "◐",
            "started from here, but nothing answers on the port",
        ),
        console.TENU: (
            "⚠",
            "something todo did not start holds that port; not stopped here",
        ),
        console.INCONNU: ("?", "cannot tell; nothing is offered"),
    }

    # Ce qu'un arrêt a donné.
    ARRETS = {
        console.ARRET_FAIT: "signal sent to the whole group",
        console.ARRET_TENACE: "still there after the signal",
        console.ARRET_REFUSE: (
            "refused: that PID no longer carries the console"
        ),
        console.ARRET_IMPOSSIBLE: "the signal could not be sent",
    }

    def _setops_console_etat(self, env=None):
        """(mot, pid, suivi) de la console, sur trois faits mesurés.

        Les trois faits sont pris À CHAQUE VISITE, sans rien garder : une
        console arrêtée hors de todo, ou un port pris entre-temps, doivent se
        voir — un état gardé en mémoire ferait proposer d'arrêter ce qui n'est
        plus là.
        """
        chemin = console.chemin_suivi(env)
        try:
            with open(chemin, encoding="utf-8") as tenu:
                suivi = console.lit_suivi(tenu.read())
        except FileNotFoundError:
            # Aucun suivi : le cas NORMAL d'une console jamais lancée d'ici.
            suivi = None
        except OSError:
            # PRÉSENT MAIS ILLISIBLE, ce qui n'est pas la même nouvelle. Traité
            # comme une absence, l'écran affirmait un FAIT FAUX — « quelque
            # chose que todo n'a pas lancé tient ce port » — alors que c'est
            # todo qui l'a lancée, et l'opérateur laissait tourner une console
            # sans authentification en croyant au travail d'autrui.
            print(f"  ? {t('the record is there but unreadable:')} {chemin}")
            return console.INCONNU, 0, None
        portee = (
            console.tenue(console.ligne_de_commande(suivi.pid))
            if suivi is not None
            else False
        )
        occupe = console.port_occupe(console.ADRESSE, console.PORT)
        mot, pid = console.situation(suivi, portee, occupe)
        if mot == console.ARRETEE and suivi is not None:
            # Le suivi désigne un processus qui n'est plus là et un port qui
            # ne répond pas : le garder ferait relire un PID mort à chaque
            # visite, et un PID se réattribue.
            console.oublie(chemin)
            suivi = None
        return mot, pid, suivi

    def _setops_console(self):
        """La console web du moteur, sur la boucle locale et rien d'autre.

        L'AVERTISSEMENT VIENT AVANT L'ÉTAT, et non en note de bas d'écran :
        une console sans authentification se juge avant de la lancer, pas
        après. Ce qui atteint son port lit tout l'inventaire et déclenche ses
        gestes.
        """
        moteur = self._setops_moteur()
        if not moteur:
            return
        print("\n🤖 " + t(console.GESTE))
        self._setops_bandeau(moteur)
        self._setops_dire_sans_serrure()
        mot, pid, suivi = self._setops_console_etat()
        marque, dit = self.CONSOLES[mot]
        adresse = console.url()
        print(f"\n  {marque} {adresse}  {t(dit)}")
        if mot == console.VIVANTE:
            print(f"      {t('process group')}: {pid}")
        self._setops_gestes_console(moteur, mot, suivi)

    def _setops_dire_sans_serrure(self):
        """Ce que la console laisse faire à qui l'atteint, et par où l'atteindre.

        La redirection SSH n'est pas un pis-aller : elle REMET
        l'authentification à SSH, là où lier largement la supprimerait.
        """
        print(
            "\n  ⚠ "
            + t(
                "This console has NO authentication: whatever reaches its port"
                " reads the whole inventory and triggers its gestures."
            )
        )
        hote, en_ssh = self._qemu_self_address()
        print(
            "    "
            + t("To reach it from elsewhere, forward the port over SSH:")
        )
        print("      " + console.redirection(hote, os.environ.get("USER", "")))
        if not en_ssh:
            print(f"  ⚠ {t('Not in an SSH session: check the host address.')}")

    def _setops_gestes_console(self, moteur, mot, suivi):
        """Ce que l'écran offre, selon ce qu'il a mesuré.

        Rien n'est offert sur un doute ni sur un port tenu par un autre :
        lancer une seconde console lui disputerait le port, et arrêter ce que
        todo n'a pas lancé porterait sur le travail de quelqu'un d'autre.
        """
        if mot == console.ARRETEE:
            geste, invite = "lancer", t("Start it")
        elif mot in (console.VIVANTE, console.MUETTE):
            # MUETTE aussi : le processus est le NÔTRE, donc l'arrêter ne
            # touche que notre groupe. Ne rien offrir laisserait un `make`
            # détaché sans console, que todo refuserait ensuite d'arrêter.
            geste, invite = "arreter", t("Stop it")
        else:
            return
        print(f"\n  [1] {invite}")
        brut = saisir(t("Which gesture? (number, empty to leave): ")).strip()
        if brut != "1":
            return
        if geste == "lancer":
            self._setops_console_lancer(moteur)
        else:
            self._setops_console_arreter(suivi)

    def _setops_console_lancer(self, moteur):
        """Lance la console détachée, puis VÉRIFIE qu'elle écoute.

        `--hote` n'est jamais passé : le moteur lie 127.0.0.1 par défaut, et
        c'est ce défaut qu'on laisse faire. Un détaché échoue en silence, donc
        le port est sondé après coup — sans quoi l'écran annoncerait une
        console qui n'a jamais démarré, et renverrait vers une page morte.
        """
        argv = runner.cible(
            os.path.relpath(moteur, RACINE), console.CIBLE, (), False
        )
        journal = console.chemin_journal()
        print(f"\n▶ {runner.cite(argv)}")
        pid = runner.detacher(
            argv,
            env=ansible_env.environnement(RACINE, moteur, runner.base()),
            cwd=RACINE,
            journal=journal,
        )
        if pid is None:
            print(f"  ✗ {t('the gesture could not run at all')}")
            return
        if not console.ecrit_suivi(console.chemin_suivi(), pid, console.PORT):
            # Sans suivi, la visite suivante ne reconnaîtra plus cette console
            # et n'offrira plus de l'arrêter. Le dire ICI : l'écran imprimait
            # ✅ et l'opérateur découvrait la perte en revenant.
            print(
                f"  ⚠ {t('the record could not be written:')} {console.chemin_suivi()}"
            )
            print(f"    {t('todo will not offer to stop it; do it by hand.')}")
        debout = console.attendre(
            lambda: console.port_occupe(console.ADRESSE, console.PORT),
            True,
            pause=lambda: time.sleep(0.2),
        )
        if debout is True:
            print(f"  ✅ {console.url()}  ({t('process group')}: {pid})")
            return
        if debout is None:
            # LA SONDE A ÉCHOUÉ, ce qui ne dit rien du serveur. Confondu avec
            # « elle n'a pas démarré », le message renvoyait vers un journal
            # qui ne contient aucune panne.
            print(f"  ? {t('the port could not be probed; state unknown.')}")
            return
        print(f"  ✗ {t('it did not come up; the log says why:')} {journal}")

    def _setops_console_arreter(self, suivi):
        """Arrête la console, et vérifie que le port est rendu.

        Le signal va au GROUPE : la recette `make` et le serveur qu'elle lance
        y sont tous les deux, et signaler le seul `make` laisserait le serveur
        tenir le port. La ligne de commande du PID est relue JUSTE AVANT — un PID
        se recycle, et le groupe visé serait celui d'un autre travail.
        """
        portee = (
            console.tenue(console.ligne_de_commande(suivi.pid))
            if suivi is not None
            else None
        )
        rendu = console.arreter(
            suivi, portee, lambda pid: os.killpg(pid, signal.SIGTERM)
        )
        if rendu != console.ARRET_FAIT:
            print(f"  ✗ {t(self.ARRETS[rendu])}")
            return
        libre = console.attendre(
            lambda: console.port_occupe(console.ADRESSE, console.PORT),
            False,
            pause=lambda: time.sleep(0.2),
        )
        if libre is False:
            console.oublie(console.chemin_suivi())
            print(f"  ✅ {t(self.ARRETS[console.ARRET_FAIT])}")
            return
        print(f"  ✗ {t(self.ARRETS[console.ARRET_TENACE])} ({suivi.pid})")

    # --- Gestes d'écriture --------------------------------------------------

    # ONZE PORTES, UN SEUL ÉCRAN. Chaque méthode ne fait que nommer sa cible :
    # tout ce qui décrit le geste — libellé, pourquoi, nature, portée, durée,
    # variables et leurs invites — est relu au registre à chaque visite. Deux
    # endroits qui décriraient le même geste diraient tôt ou tard deux choses
    # différentes, et c'est le registre qui a raison.

    def _setops_geste_instancier(self):
        return self._setops_geste("instancier")

    def _setops_geste_instancier_appliquer(self):
        return self._setops_geste("instancier-appliquer")

    def _setops_geste_deployer(self):
        return self._setops_geste("deployer")

    def _setops_geste_deployer_groupe(self):
        return self._setops_geste("deployer-groupe")

    def _setops_geste_appliquer(self):
        return self._setops_geste("appliquer")

    def _setops_geste_creer_vm(self):
        return self._setops_geste("creer-vm")

    def _setops_geste_flotte_creer(self):
        return self._setops_geste("flotte-creer")

    def _setops_geste_flux(self):
        return self._setops_geste("flux")

    def _setops_geste_site(self):
        return self._setops_geste("site")

    def _setops_geste_genome_inscrire(self):
        return self._setops_geste("genome-inscrire")

    def _setops_geste_config(self):
        return self._setops_geste("config")

    def _setops_geste(self, cible):
        """La porte d'un geste d'écriture. TOUT VIENT DU REGISTRE.

        La barrière est celle du navigateur — `runbooks.barriere` — et non une
        seconde règle : une porte dédiée qui jugerait elle-même le périmètre
        finirait par conduire ce que le navigateur refuse, ou l'inverse.
        """
        moteur = self._setops_moteur()
        if not moteur:
            return
        print("\n🤖 " + t(registre.PORTES[cible]))
        self._setops_bandeau(moteur)
        lus = self._setops_registre(moteur)
        if lus is None:
            return
        etape = registre.trouve(lus, cible)
        if etape is None:
            manque = t("the registry declares no single « {cible} »")
            print(f"  ✗ {manque.format(cible=cible)}")
            return
        self._setops_dire_geste(etape)
        barriere = registre.barriere(
            etape,
            ecosystems.monte(moteur),
            ecosystems.site_monte(moteur),
            confirme=registre.destructeur(etape),
        )
        if barriere:
            print(f"  ⛔ {t(self.BARRIERES[barriere])}")
            return
        self._setops_jouer_etape(moteur, etape)

    def _setops_dire_geste(self, etape):
        """Ce que le registre dit de ce geste, avec ses mots.

        La nature et la portée sont AFFICHÉES plutôt que sous-entendues par
        l'entrée de menu : une porte dédiée fait oublier dans quelle séquence
        le geste vit, et donc ce qu'il suppose déjà fait.
        """
        marque = self.MARQUES_NATURE.get(etape.nature, "?")
        print(f"\n  {marque} make {etape.cible}  [{etape.portee}]")
        if etape.libelle:
            print(f"      {etape.libelle}")
        if etape.duree:
            print(f"      {t('takes')} {etape.duree}")

    # --- L'épingle -----------------------------------------------------------

    # Ce qu'une réponse de la forge dit à l'écran. Vocabulaire CLOS : trois
    # réponses, parce que la troisième est celle qui coûte cher.
    FORGE = {
        "pointe": "the forge carries",
        "effacee": (
            "that branch is NO LONGER on the forge: a fresh station cannot"
            " fetch this pin"
        ),
        "muette": "could not ask the forge",
    }

    def _setops_epingle(self):
        """Faire avancer l'épingle, et d'abord savoir ce que la forge porte.

        LA SONDE EST UN GESTE, pas un effet de bord de l'affichage : elle sort
        de la machine, et un écran qui parlerait au réseau en s'ouvrant le
        ferait à chaque passage.

        LE COMMIT RESTE CELUI DE L'EXPLOITANT. Cet écran réécrit un attribut du
        manifeste et s'arrête là : ce qui part dans l'historique se relit et se
        signe ailleurs.
        """
        decl = engine.declaration(RACINE)
        if decl is None or not decl.path:
            print(f"  ✗ {t('the manifest declares no engine')}")
            return
        moteur = os.path.join(RACINE, decl.path)
        print("\n🤖 " + t(engine.GESTE_EPINGLE))
        print(f"  {t('pinned')} : {decl.revision}")
        print(f"  {t('branch')} : {decl.upstream or '?'}")
        if not os.path.isdir(moteur):
            print(
                f"  ◐ {t('the engine is not here yet; see the state screen')}"
            )
            return
        relation, ecart = engine.relation_to_pin(moteur, decl.revision)
        print(f"  {t('the clone against the pin')} : {relation} ({ecart})")
        print(
            "\n  [1] "
            + t("Ask the forge what it carries (network; writes nothing here)")
        )
        if (
            saisir(t("Which gesture? (number, empty to leave): ")).strip()
            != "1"
        ):
            return
        self._setops_sonder_forge(moteur, decl)

    def _setops_sonder_forge(self, moteur, decl):
        """Interroge chaque remote jusqu'à une réponse, et dit laquelle a parlé.

        LES DEUX REMOTES D'UNE MÊME FORGE ne se valent pas : l'un passe par
        HTTPS, l'autre par ssh, et un seul répond sans identifiants. Les essayer
        est la seule façon de ne pas dépendre de celui qui se tait.
        """
        noms = engine.remotes(moteur)
        if not noms:
            print(f"  ✗ {t('the clone declares no remote')}")
            return
        for nom in noms:
            pointe = engine.pointe_distante(moteur, nom, decl.upstream)
            if pointe is None:
                print(f"  ? {nom} : {t(self.FORGE['muette'])}")
                continue
            if not pointe:
                # LE CAS QUI COÛTE CHER, et il est silencieux autrement : une
                # branche de côté s'efface après sa fusion, et l'épingle qui la
                # visait devient irrapatriable — pendant que ce poste, déjà
                # cloné, continue de marcher sans rien dire.
                print(f"  ⛔ {nom} : {t(self.FORGE['effacee'])}")
                return
            print(f"  ✔ {nom} : {t(self.FORGE['pointe'])} {pointe}")
            self._setops_comparer_pointe(moteur, decl, nom, pointe)
            return
        print(f"  ✗ {t('no remote answered; the lag is unknown')}")

    def _setops_comparer_pointe(self, moteur, decl, remote, pointe):
        """Dit ce qui sépare l'épingle de la pointe, puis propose de l'avancer."""
        if pointe == decl.revision:
            print(f"  ✅ {t('the pin is already the forge tip')}")
            return
        print(
            f"\n  {t('bringing the objects down to read what separates them')}"
        )
        if not engine.rapatrier(moteur, remote, decl.upstream):
            print(f"  ✗ {t('the objects could not be fetched')}")
            return
        lus = engine.journal(moteur, decl.revision, pointe)
        if lus is None:
            print(f"  ✗ {t('the range between the two could not be read')}")
            return
        compte = t("{n} commit(s) the pin would gain").format(n=len(lus))
        print(f"  {compte}")
        for court, sujet in lus:
            print(f"    {court} {sujet}")
        self._setops_avancer_epingle(decl, pointe)

    def _setops_avancer_epingle(self, decl, pointe):
        """Réécrit la révision du manifeste, et s'arrête là.

        UN SEUL ATTRIBUT CHANGE, commentaires compris : ils portent la raison de
        l'épingle. Et le commit reste celui de l'exploitant — ce qui part dans
        l'historique se relit avant d'être signé.
        """
        chemin = os.path.join(RACINE, engine.MANIFEST)
        print(
            f"\n  ⚠ {t('This rewrites one attribute of:')} {engine.MANIFEST}"
        )
        print(f"    {t('The commit stays yours; nothing is committed here.')}")
        demande = t("Advance the pin to {sha}? (y/N): ").format(
            sha=pointe[:12]
        )
        if not self._is_yes(saisir(demande)):
            print(t("Cancelled."))
            return
        try:
            with open(chemin, encoding="utf-8") as tenu:
                avant = tenu.read()
        except OSError as souci:
            print(f"  ✗ {souci.strerror or souci}")
            return
        apres = engine.reecrire_revision(avant, pointe)
        if apres is None:
            print(
                f"  ✗ {t('the manifest does not carry exactly one revision')}"
            )
            return
        try:
            with open(chemin, "w", encoding="utf-8") as tenu:
                tenu.write(apres)
        except OSError as souci:
            print(f"  ✗ {souci.strerror or souci}")
            return
        print(f"  ✅ {t('the pin now reads')} {pointe}")
        print(f"    {t('read the diff, then commit it yourself.')}")
