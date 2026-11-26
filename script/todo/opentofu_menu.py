#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Menu OpenTofu : des parcs de VM décrits par une spec, appliqués par un
moteur.

Le menu ne parle qu'à l'interface de `script.opentofu.moteur` : chaque
opération passe par `moteur_pour(spec)` et le journal du moteur s'affiche
ligne à ligne. Un apply qui remplace ou détruit une VM, et tout destroy,
exigent de retaper le nom du parc ; un refus n'appelle jamais le moteur.
Après un apply réussi, chaque VM reçoit son alias `<hôte>+<vm>` dans
~/.ssh/config, avec l'hôte Proxmox pour rebond, puis les VM marquées
`installer_erplibre` passent par l'installation suivie du menu QEMU/KVM.

Mixin : ses méthodes vivent sur la classe TODO et réutilisent les helpers
Proxmox (`_pve_host`, `_pve_host_pinned`, `_pve_guest_ip`,
`_pve_attendre_ssh`) et ssh (`_write_ssh_config_entry`, `_ssh_private_key`,
`_ssh_config_block`) plutôt que de les redire.
"""

import re
import shlex
import subprocess

import click

from script.opentofu import coffre, jeton_proxmox, moteur, outil, resolution
from script.opentofu import spec as spec_parc
from script.todo.todo_i18n import t


class OpenTofuMenuMixin:
    """Menu OpenTofu : créer, planifier, appliquer et détruire un parc."""

    def prompt_execute_opentofu(self):
        """Sous-menu OpenTofu. Chaque entrée porte sa méthode dans
        `"method"` : le numéro affiché est le seul qui existe, aucune
        chaîne de `elif` ne le recopie."""
        print(f"🤖 {t('Deploy a fleet with OpenTofu!')}")
        choices = [
            {"section": t("Fleets")},
            {
                "prompt_description": t("Create a fleet"),
                "method": "_tofu_creer_parc",
            },
            {
                "prompt_description": t("Edit a fleet (form)"),
                "method": "_tofu_editer_parc",
            },
            {
                "prompt_description": t("List the fleets"),
                "method": "_tofu_lister_parcs",
            },
            {"section": t("Operations")},
            {
                "prompt_description": t("Plan (preview the changes)"),
                "method": "_tofu_plan",
            },
            {
                "prompt_description": t(
                    "Apply the plan (create or update the VMs)"
                ),
                "method": "_tofu_apply",
            },
            {
                "prompt_description": t("Destroy the fleet VMs"),
                "method": "_tofu_destroy",
            },
            {
                "prompt_description": t("Show the tofu state"),
                "method": "_tofu_etat",
            },
            {
                "prompt_description": t("Show the VM addresses"),
                "method": "_tofu_adresses",
            },
            {"section": t("Proxmox")},
            {
                "prompt_description": t(
                    "Prepare the host (role, user, API token)"
                ),
                "method": "_tofu_preparer_hote",
            },
            {"section": t("Tool")},
            {
                "prompt_description": t("Check or install tofu"),
                "method": "_tofu_outil",
            },
        ]
        # Ce que todo.json ajoute s'affiche à la suite et se lance par son
        # numéro, comme dans les menus QEMU/KVM et Proxmox.
        choices.extend(
            self.config_file.get_config("opentofu_from_makefile") or []
        )
        help_info = self.fill_help_info(choices)
        reelles = [c for c in choices if not c.get("section")]
        while True:
            status = click.prompt(help_info)
            print()
            if status == "0":
                return False
            numero = int(status) if status.isdigit() else 0
            if not 0 < numero <= len(reelles):
                print(t("Command not found !"))
                continue
            entree = reelles[numero - 1]
            if entree.get("method"):
                getattr(self, entree["method"])()
            else:
                self.execute_from_configuration(entree)

    # ------------------------------------------------------------------ #
    # Parcs : choix, lecture, moteur
    # ------------------------------------------------------------------ #

    @staticmethod
    def _tofu_racine():
        """Dossier des parcs, lu à chaque appel et non à l'import : le
        remplacer sur le module `spec` suffit à déplacer tout le menu."""
        return spec_parc.RACINE_PARCS

    @staticmethod
    def _tofu_journal(ligne):
        """Journal du moteur : une ligne, déjà expurgée, affichée aussitôt."""
        print(f"  {ligne}", flush=True)

    @staticmethod
    def _tofu_alias(spec, vm):
        """`<hôte>+<vm>`, la convention des VM Proxmox : l'hôte est la cible
        ssh sans son compte, réduite aux caractères d'un nom `Host`."""
        hote = spec["cible"]["hote"]["target"].split("@")[-1]
        hote = re.sub(r"[^A-Za-z0-9._-]", "-", hote) or "pve"
        return f"{hote}+{vm}"

    def _tofu_choisir_parc(self):
        """Nom du parc choisi dans la liste numérotée, ou None."""
        parcs = spec_parc.lister(self._tofu_racine())
        if not parcs:
            print(t("No fleet yet: create one first."))
            return None
        print(f"\n{t('Which fleet?')}")
        for i, nom in enumerate(parcs, start=1):
            print(f"  [{i}] {nom}")
        choix = input(t("Choice: ")).strip()
        if choix.isdigit() and 0 < int(choix) <= len(parcs):
            return parcs[int(choix) - 1]
        print(t("Cancelled."))
        return None

    def _tofu_charger(self, nom):
        """Spec valide du parc `nom`, ou None après avoir listé ses
        erreurs : une spec abîmée à la main donne un message, pas une
        trace."""
        try:
            return spec_parc.charger(nom, self._tofu_racine())
        except spec_parc.SpecInvalide as exc:
            print("✗ " + t("Invalid spec for fleet {nom}:").format(nom=nom))
            for erreur in exc.erreurs:
                print(f"    - {erreur}")
            return None

    def _tofu_parc(self):
        """Spec du parc choisi, ou None."""
        nom = self._tofu_choisir_parc()
        return self._tofu_charger(nom) if nom else None

    def _tofu_executer(self, spec):
        """Exécuteur des commandes de l'hôte de `spec`, ou None.

        Bâti sur `pve.run` et `wrap_privilege` (`resolution.executer_ssh`).
        `resolution.elevation` décide de l'élévation : root, ou un sudo
        qui ne demande pas de mot de passe ; sinon sa raison s'affiche.
        """
        hote = spec["cible"]["hote"]
        brut = resolution.executer_ssh({**hote, "sudo": ""})
        sudo, raison = resolution.elevation(brut)
        if sudo is None:
            print(f"  ✗ {hote['target']} : {raison}")
            return None
        return resolution.executer_ssh({**hote, "sudo": sudo})

    def _tofu_moteur(self, spec, executer=None):
        """Moteur que la spec désigne, ou None (message affiché)."""
        kw = {"racine": self._tofu_racine()}
        if executer is not None:
            kw["executer"] = executer
        try:
            return moteur.moteur_pour(spec, **kw)
        except KeyError as exc:
            print(f"✗ {exc.args[0] if exc.args else exc}")
            return None
        except TypeError as exc:
            # Un moteur qui ne suit pas le contrat de `Moteur.__init__`.
            print(
                "✗ "
                + t("Engine {nom} cannot start: {err}").format(
                    nom=spec.get("moteur"), err=exc
                )
            )
            return None

    def _tofu_nom_retape(self, spec):
        """Vrai si l'opérateur retape exactement le nom du parc."""
        saisi = input(
            t("Type the fleet name ({nom}) to confirm: ").format(
                nom=spec["nom"]
            )
        ).strip()
        if saisi == spec["nom"]:
            return True
        print(t("The name does not match: cancelled."))
        return False

    def _tofu_retirer_alias(self, spec, noms_vm):
        """Retire de ~/.ssh/config les alias des VM `noms_vm` du parc.

        Seul un bloc qui rebondit par l'hôte du parc est retiré : un
        homonyme qui passe par un autre rebond n'appartient pas au parc.
        """
        cible = spec["cible"]["hote"]["target"]
        alias = [
            a
            for a in (self._tofu_alias(spec, n) for n in noms_vm)
            if self._ssh_config_block(a).get("proxyjump") == cible
        ]
        if alias:
            self._write_ssh_config_entry([], "", "", also_drop=alias)

    # ------------------------------------------------------------------ #
    # Entrées « Parcs »
    # ------------------------------------------------------------------ #

    def _tofu_creer_parc(self):
        """Crée la spec d'un parc : un nom, l'hôte Proxmox, une VM par
        défaut. L'hôte mémorisé par le menu Proxmox est proposé d'office."""
        racine = self._tofu_racine()
        nom = input(t("Fleet name (lowercase letters, digits, dash): "))
        nom = nom.strip()
        try:
            spec_parc.dossier_parc(nom, racine)
        except ValueError as exc:
            print(f"✗ {exc}")
            return
        if nom in spec_parc.lister(racine):
            print("✗ " + t("Fleet {nom} already exists.").format(nom=nom))
            return
        memo = self._pve_host(ask=False) or {}
        defaut = memo.get("target") or ""
        if defaut:
            invite = t("SSH target of the Proxmox host [{defaut}]: ").format(
                defaut=defaut
            )
        else:
            invite = t(
                "SSH target of the Proxmox host (user@host or ssh alias): "
            )
        cible = input(invite).strip() or defaut
        if not cible:
            print(t("Cancelled."))
            return
        spec = spec_parc.nouvelle_spec(nom, cible)
        erreurs = spec_parc.valider(spec)
        if erreurs:
            for erreur in erreurs:
                print(f"✗ {erreur}")
            return
        chemin = spec_parc.sauver(spec, racine)
        print(
            "✓ "
            + t("Fleet {nom} saved in {chemin}.").format(
                nom=nom, chemin=chemin
            )
        )
        if self._is_yes(input(t("Open the fleet form now? [y/N] "))):
            self._tofu_editer_parc(nom)

    def _tofu_editer_parc(self, nom=None):
        """Ouvre le formulaire du parc ; il sauve par `enregistrer`, et un
        apply réussi y mène, écran fermé, à `_tofu_apres_apply`."""
        try:
            from script.todo.opentofu_form import run_opentofu_form
        except ModuleNotFoundError as exc:
            # Seule l'absence du module du formulaire lui-même vaut « pas
            # encore livré » ; une dépendance manquante est une vraie panne.
            if exc.name != "script.todo.opentofu_form":
                print(f"✗ {exc}")
                return
            print(t("The fleet form (TUI) is not available yet."))
            return
        except ImportError as exc:
            print(f"✗ {exc}")
            return
        nom = nom or self._tofu_choisir_parc()
        spec = self._tofu_charger(nom) if nom else None
        if not spec:
            return
        mot = self._tofu_moteur(spec)
        if mot is None:
            return
        racine = self._tofu_racine()
        # Un apply ou un destroy lancé du formulaire mène aux mêmes suites
        # que celui du menu, une fois l'écran fermé.
        run_opentofu_form(
            spec,
            mot,
            lambda s: spec_parc.sauver(s, racine),
            quand_applique=lambda s, n, d: self._tofu_suites_apply(
                s, mot, n, d
            ),
            quand_detruit=lambda s: self._tofu_apres_destroy(s),
        )

    def _tofu_lister_parcs(self):
        """Une ligne par parc : VM et hôte, ou ses erreurs de spec."""
        racine = self._tofu_racine()
        noms = spec_parc.lister(racine)
        if not noms:
            print(t("No fleet yet: create one first."))
            return
        print(t("Fleets in {racine}:").format(racine=racine))
        for nom in noms:
            try:
                spec = spec_parc.charger(nom, racine)
            except spec_parc.SpecInvalide as exc:
                print(f"  ✗ {nom} — {t('invalid spec')}")
                for erreur in exc.erreurs:
                    print(f"      - {erreur}")
                continue
            ligne = t("{n} VM(s) on {cible}").format(
                n=len(spec["vms"]), cible=spec["cible"]["hote"]["target"]
            )
            print(f"  {nom} — {ligne}")

    # ------------------------------------------------------------------ #
    # Entrées « Opérations »
    # ------------------------------------------------------------------ #

    def _tofu_planifier(self, spec):
        """(moteur, changements) d'un plan réussi et affiché, sinon None.

        Le moteur met la spec à jour en place quand la résolution remplit
        des champs : l'appelant applique et lit les sorties sur ces valeurs.
        """
        executer = self._tofu_executer(spec)
        if executer is None:
            return None
        mot = self._tofu_moteur(spec, executer)
        if mot is None:
            return None
        res, changements = mot.planifier(spec, self._tofu_journal)
        if not res.ok:
            print(f"✗ {res.message}")
            return None
        if res.message:
            print(f"✓ {res.message}")
        print()
        for ligne in moteur.formater_plan(changements):
            print(f"  {ligne}")
        return mot, changements

    def _tofu_plan(self):
        """Plan du parc choisi, affiché sans rien appliquer."""
        spec = self._tofu_parc()
        if spec:
            self._tofu_planifier(spec)

    def _tofu_apply(self):
        """Planifie, montre le plan, confirme, applique, puis l'après-apply.

        Un plan qui remplace ou détruit une ressource exige de retaper le
        nom du parc ; sinon un oui suffit. Les suites (`_tofu_suites_apply`)
        retirent les alias des VM que le plan détruit sans les garder dans
        la spec, et n'attendent et n'installent que les VM que le plan crée
        ou remplace.
        """
        spec = self._tofu_parc()
        if not spec:
            return
        plan = self._tofu_planifier(spec)
        if plan is None:
            return
        mot, changements = plan
        if not changements:
            print(t("Nothing to apply."))
            return
        if moteur.est_destructeur(changements):
            print(f"\n⚠ {t('This plan replaces or destroys VMs.')}")
            if not self._tofu_nom_retape(spec):
                return
        elif not self._is_yes(input(t("Apply this plan? [y/N] "))):
            print(t("Cancelled."))
            return
        res = mot.appliquer(spec, self._tofu_journal)
        if not res.ok:
            print(f"✗ {res.message}")
            return
        print(f"✓ {res.message}")
        self._tofu_suites_apply(
            spec,
            mot,
            moteur.vms_nouvelles(changements),
            moteur.vms_detruites(changements, spec),
        )

    def _tofu_destroy(self):
        """Détruit les VM du parc après que son nom a été retapé."""
        spec = self._tofu_parc()
        if not spec:
            return
        vms = ", ".join(vm["nom"] for vm in spec["vms"])
        avis = t("This destroys every VM of fleet {nom}: {vms}")
        print("⚠ " + avis.format(nom=spec["nom"], vms=vms))
        if not self._tofu_nom_retape(spec):
            return
        mot = self._tofu_moteur(spec)
        if mot is None:
            return
        res = mot.detruire(spec, self._tofu_journal)
        if not res.ok:
            print(f"✗ {res.message}")
            return
        print(f"✓ {res.message}")
        self._tofu_apres_destroy(spec)

    def _tofu_etat(self):
        """Ressources que l'état du parc connaît."""
        spec = self._tofu_parc()
        mot = self._tofu_moteur(spec) if spec else None
        if mot is None:
            return
        lignes = mot.etat(spec)
        if not lignes:
            print(t("Empty state: nothing applied yet."))
        for ligne in lignes:
            print(f"  {ligne}")

    def _tofu_adresses(self):
        """VMID, adresse et alias ssh de chaque VM, d'après les sorties."""
        spec = self._tofu_parc()
        mot = self._tofu_moteur(spec) if spec else None
        if mot is None:
            return
        sorties = mot.sorties(spec)
        if not sorties:
            print(t("No outputs: apply the fleet first."))
            return
        for nom in sorted(sorties):
            sortie = sorties[nom]
            ip = sortie.get("ip") or t("DHCP (address known by the host)")
            alias = self._tofu_alias(spec, nom)
            print(f"  {nom}  vmid {sortie.get('vmid')}  {ip}  ssh {alias}")

    # ------------------------------------------------------------------ #
    # Après l'apply, après le destroy
    # ------------------------------------------------------------------ #

    def _tofu_suites_apply(self, spec, mot, nouvelles, detruites):
        """Suites d'un apply réussi, du menu comme du formulaire : retire
        les alias des VM `detruites`, puis `_tofu_apres_apply` sur les
        sorties du moteur `mot`."""
        if detruites:
            self._tofu_retirer_alias(spec, sorted(detruites))
        self._tofu_apres_apply(spec, mot.sorties(spec), nouvelles)

    def _tofu_apres_apply(self, spec, sorties, nouvelles=None):
        """Alias ssh, attente de ssh, puis installation suivie d'ERPLibre.

        L'adresse vient de la sortie (adresse fixe de la spec) ; vide (DHCP),
        elle est demandée à l'hôte par `_pve_guest_ip`, l'hôte de la spec
        étant épinglé le temps de l'appel. L'alias rebondit par l'hôte :
        l'adresse d'une VM sur un pont interne n'est routable que de lui.

        `nouvelles` : noms des VM que l'apply a créées ou remplacées ; None
        les vise toutes. L'alias est réécrit pour toute VM dont l'adresse se
        lit sans attendre ; l'attente de l'adresse, celle de ssh et
        l'installation ne visent que les nouvelles, pour qu'un apply qui
        retouche une VM ne réinstalle pas ses voisines. Une VM sans VMID,
        sans adresse ou muette en ssh est signalée et sautée.
        """
        hote = spec["cible"]["hote"]
        cible = hote["target"]
        compte = spec.get("compte") or {}
        user = compte.get("user") or ""
        cle = self._ssh_private_key(compte.get("ssh_key") or "")
        epingle = {
            "target": cible,
            "jump": hote.get("jump") or "",
            "port": hote.get("port") or "",
            "sudo": hote.get("sudo") or "",
        }
        alias, cartes = {}, {}
        with self._pve_host_pinned(epingle):
            for vm in spec["vms"]:
                nom = vm["nom"]
                neuve = nouvelles is None or nom in nouvelles
                sortie = sorties.get(nom)
                if not sortie:
                    avis = t("{vm}: no tofu output, skipped.")
                    print("  ⚠ " + avis.format(vm=nom))
                    continue
                vmid = sortie.get("vmid") or vm.get("vmid")
                ip = sortie.get("ip") or ""
                if not ip and not vmid:
                    avis = t("{vm}: no VMID known, skipped.")
                    print("  ⚠ " + avis.format(vm=nom))
                    continue
                if not ip and neuve:
                    ip = self._pve_guest_ip(vmid)
                elif not ip:
                    # Une VM déjà en place a son bail : une seule lecture.
                    ip = self._pve_guest_ip(vmid, attente=0)
                if not ip:
                    avis = t(
                        "{vm}: no address yet; see Show the VM addresses "
                        "later."
                    )
                    print("  ⚠ " + avis.format(vm=nom))
                    continue
                nom_alias = self._tofu_alias(spec, nom)
                self._write_ssh_config_entry(
                    nom_alias,
                    user,
                    ip,
                    proxy_jump=cible,
                    identity_file=cle or None,
                )
                if not neuve:
                    continue
                if not self._pve_attendre_ssh(nom_alias):
                    avis = t("{vm}: does not answer ssh yet.")
                    print("  ⚠ " + avis.format(vm=nom))
                    continue
                alias[nom] = nom_alias
                cartes[nom] = {
                    "target": cible,
                    "sudo": epingle["sudo"],
                    "jump": epingle["jump"],
                    "vmid": vmid,
                    "addr": ip,
                }
            a_installer = [
                vm
                for vm in spec["vms"]
                if vm.get("installer_erplibre") and vm["nom"] in alias
            ]
            if not a_installer:
                return
            noms = [vm["nom"] for vm in a_installer]
            branches = {
                vm["nom"]: vm.get("branche") or "" for vm in a_installer
            }
            commune = next(iter(branches.values())) if branches else ""
            branche = (
                branches if self._qemu_per_vm(branches, commune) else commune
            )
            self._qemu_install_erplibre_monitored(
                noms,
                branche,
                {n: alias[n] for n in noms},
                pve={n: cartes[n] for n in noms},
                meta={
                    vm["nom"]: (vm["distro"], vm["version"], vm["arch"])
                    for vm in a_installer
                },
                users=dict.fromkeys(noms, user),
            )

    def _tofu_apres_destroy(self, spec):
        """Retire les alias ssh des VM du parc détruit."""
        self._tofu_retirer_alias(spec, [vm["nom"] for vm in spec["vms"]])

    # ------------------------------------------------------------------ #
    # Entrées « Proxmox » et « Outil »
    # ------------------------------------------------------------------ #

    def _tofu_preparer_hote(self):
        """Rôle, utilisateur et jeton d'API du parc sur l'hôte Proxmox.

        L'exécuteur passé est BRUT (sans sudo) : `preparer_hote` mesure
        lui-même l'élévation et la pose dans la spec rendue, sauvée ici
        seulement si la préparation réussit.
        """
        spec = self._tofu_parc()
        if not spec:
            return
        hote = spec["cible"]["hote"]
        annonce = t(
            "Preparing {cible}: role {role}, user {user}, token {jeton}."
        )
        print(
            annonce.format(
                cible=hote["target"],
                role=jeton_proxmox.ROLE,
                user=jeton_proxmox.UTILISATEUR,
                jeton=f"{jeton_proxmox.UTILISATEUR}!{spec['nom']}",
            )
        )
        recreer = self._is_yes(
            input(
                t(
                    "Recreate the fleet API token (the current one stops "
                    "working)? [y/N] "
                )
            )
        )
        brut = resolution.executer_ssh({**hote, "sudo": ""})
        racine = self._tofu_racine()
        res, neuve = jeton_proxmox.preparer_hote(
            spec, brut, recreer=recreer, racine=racine
        )
        if not res.ok:
            print(f"✗ {res.message}")
            return
        if neuve != spec:
            spec_parc.sauver(neuve, racine)
        print(f"✓ {res.message}")

    def _tofu_outil(self):
        """Montre `tofu` et sa version ; absent ou trop vieux, propose le
        paquet de la distribution puis l'archive signée de l'éditeur."""
        try:
            conf = coffre.charger_conf()
        except (OSError, ValueError) as exc:
            print(f"✗ {exc}")
            return
        plancher = conf["required_version"]
        binaire = outil.trouver_tofu()
        if binaire:
            version = outil.version_tofu(binaire)
            vu = t("tofu: {chemin}, version {version}")
            print("  " + vu.format(chemin=binaire, version=version or "?"))
            if self._tofu_version_ok(version, plancher):
                return
        else:
            print(f"✗ {t('tofu is not installed.')}")
        if self._tofu_installer_paquet(plancher):
            return
        question = t(
            "Install tofu {version} from the signed upstream archive into "
            "~/.local/bin? [y/N] "
        ).format(version=conf["version"])
        if not self._is_yes(input(question)):
            print(t("Cancelled."))
            return
        res = outil.installer_zip(conf)
        print(f"{'✓' if res.ok else '✗'} {res.message}")

    def _tofu_installer_paquet(self, plancher):
        """Propose la commande du paquet ; vrai si elle a tourné et que le
        `tofu` trouvé ensuite satisfait `plancher`.

        La commande vient de `outil.commande_paquet` ; elle est découpée en
        argv et lancée sans shell, terminal hérité pour l'invite de sudo.
        """
        commande, _paquet = outil.commande_paquet()
        if not commande:
            return False
        print(f"  {t('Distribution package:')} {commande}")
        if not self._is_yes(input(t("Run it now? [y/N] "))):
            return False
        try:
            code = subprocess.run(
                shlex.split(commande), check=False
            ).returncode
        except OSError as exc:
            print(f"✗ {exc}")
            return False
        if code != 0:
            echec = t("The package install failed (exit {code}).")
            print("✗ " + echec.format(code=code))
            return False
        binaire = outil.trouver_tofu()
        version = outil.version_tofu(binaire) if binaire else ""
        return self._tofu_version_ok(version, plancher)

    @staticmethod
    def _tofu_version_ok(version, plancher):
        """Dit si `version` satisfait `plancher`, et le rend."""
        if outil.version_suffisante(version, plancher):
            ok = t("tofu {version} satisfies {plancher}.")
            print("✓ " + ok.format(version=version, plancher=plancher))
            return True
        ko = t("tofu {version} does not satisfy {plancher}.")
        print("⚠ " + ko.format(version=version or "?", plancher=plancher))
        return False
