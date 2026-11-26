#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Un parc OpenTofu tient-il de bout en bout sur un Proxmox jetable ?

Ce n'est pas un test unitaire : il crée une vraie machine, y installe
Proxmox VE et y applique un parc. Il vit donc hors de `test/`.

Le Proxmox est l'étage 1 de `deep_proxmox` (création QEMU locale,
install_proxmox.sh, redémarrage sur le noyau -pve, services, stockage),
nommé `test-tofu-pve-1`. Sur lui, huit étapes, chacune notée au rapport
avec son statut et sa durée :

  monter_pve     l'étage 1 de la descente, debout et contrôlé ;
  preparer_hote  pont interne, rôle, utilisateur, jeton d'API du parc ;
  plan_1         le plan crée la VM, son cloud-init et son image, rien
                 d'autre ; le `tofu show -json` du plan est gardé en 0600 ;
  apply          le plan appliqué, puis l'après-apply du menu (alias ssh) ;
  ssh            `ssh -o BatchMode=yes <alias> true` par cet alias ;
  plan_2         un second plan n'annonce aucun changement ;
  destroy        `tofu destroy`, puis le retrait de l'alias ;
  absence        `qm list` sur le Proxmox ne montre plus le VMID.

Le parc s'appelle `test-tofu` et vit dans le vrai `private/opentofu/` :
le menu OpenTofu peut l'ouvrir après la course. Le verdict porte sur l'état
constaté : code 0 seulement si les huit étapes sont `ok`.

  ./long_test/opentofu_proxmox.py               # la course, sudo demandé
  ./long_test/opentofu_proxmox.py --dry-run     # le plan, rien de créé
  ./long_test/opentofu_proxmox.py --detruire    # le Proxmox, puis le parc
"""

import argparse
import os
import shutil
import subprocess
import sys
import time

RACINE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RACINE)
sys.path.insert(0, os.path.join(RACINE, "long_test"))

import deep_proxmox  # noqa: E402
from descente import (  # noqa: E402
    Famille,
    autre_descente,
    cle_publique,
    dernier_rapport,
    detruire,
    dire,
    mener,
)

from script.opentofu import (  # noqa: E402
    coffre,
    jeton_proxmox,
    moteur,
    moteur_tofu,
    outil,
    resolution,
)
from script.opentofu import spec as spec_parc  # noqa: E402
from script.proxmox import proxmox_deploy as pve  # noqa: E402

NOM_BASE = "test-tofu-pve"
OUTIL = "opentofu_proxmox"
PARC = "test-tofu"
VM = f"{PARC}-vm-1"
ETAPES = (
    "monter_pve",
    "preparer_hote",
    "plan_1",
    "apply",
    "ssh",
    "plan_2",
    "destroy",
    "absence",
)
# Ce que le premier plan doit annoncer, et rien d'autre : (action, genre).
PLAN_1_ATTENDU = tuple(
    sorted(
        ("creer", genre)
        for genre in (
            moteur.RESSOURCE_CLOUD_INIT,
            moteur.RESSOURCE_IMAGE,
            moteur.RESSOURCE_VM,
        )
    )
)
# La VM du parc, à la mesure de l'étage 1 (4 vCPU, 4096 Mo, 25 Go) qui
# porte aussi Proxmox lui-même.
VM_RESSOURCES = {"vcpus": 1, "ram": 1024, "disque": "8G"}
DELAI_SSH = 300
DESCRIPTION = __doc__.splitlines()[0]
REMEDE_TOFU = (
    "menu OpenTofu de TODO, « Check or install tofu » (paquet de la"
    " distribution ou archive signée dans ~/.local/bin)"
)


def _racine():
    """Dossier des parcs, relu à chaque appel : le déplacer sur le module
    `spec` déplace tout ce que ce test écrit."""
    return spec_parc.RACINE_PARCS


def agent_ssh_charge():
    """Vrai si un agent ssh répond avec au moins une clé.

    Le fournisseur bpg s'authentifie en ssh par l'agent (`ssh.agent`) pour
    écrire les snippets : sans agent, l'apply échoue après l'installation
    entière du Proxmox.
    """
    try:
        res = subprocess.run(
            ["ssh-add", "-l"],
            capture_output=True,
            text=True,
            timeout=10,
            stdin=subprocess.DEVNULL,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return res.returncode == 0


def kvm_present():
    return os.path.exists("/dev/kvm")


def module_imbrique():
    """Module noyau qui porte le paramètre `nested` sur cet hôte."""
    return resolution.charger_deploy_qemu().nested_module()


def imbrication_active():
    """Vrai si `nested` vaut Y ou 1. Un fichier illisible vaut non : la VM
    du parc tournerait sans KVM dans le Proxmox, et `qm start` la refuse."""
    chemin = f"/sys/module/{module_imbrique()}/parameters/nested"
    try:
        with open(chemin, encoding="utf-8") as fh:
            return fh.read().strip() in ("Y", "1")
    except OSError:
        return False


def prealables():
    """« manque — remède » pour chaque prérequis absent ; vide si tout y est.

    Contrôlé AVANT toute création : un manque découvert après l'installation
    du Proxmox coûte une course entière.
    """
    manques = []
    try:
        conf = coffre.charger_conf()
    except (OSError, ValueError) as exc:
        conf = None
        manques.append(
            f"conf/opentofu.json illisible ({exc}) — restaurer le fichier"
            " du dépôt"
        )
    binaire = outil.trouver_tofu()
    if not binaire:
        manques.append(f"tofu absent — l'installer : {REMEDE_TOFU}")
    elif conf:
        version = outil.version_tofu(binaire)
        plancher = conf["required_version"]
        if not outil.version_suffisante(version, plancher):
            manques.append(
                f"tofu {version or '?'} ne satisfait pas {plancher} — le"
                f" mettre à jour : {REMEDE_TOFU}"
            )
    if not cle_publique():
        manques.append(
            "aucune clé publique ~/.ssh/id_ed25519.pub ni id_rsa.pub —"
            " ssh-keygen -t ed25519"
        )
    if not agent_ssh_charge():
        manques.append(
            "aucun agent ssh avec une clé : le fournisseur bpg passe par"
            ' lui — eval "$(ssh-agent)" && ssh-add'
        )
    if not kvm_present():
        manques.append(
            "/dev/kvm absent — activer la virtualisation matérielle et"
            " charger kvm_intel ou kvm_amd"
        )
    elif not imbrication_active():
        module = module_imbrique()
        manques.append(
            f"imbrication inactive (/sys/module/{module}/parameters/nested)"
            f" — « options {module} nested=1 » dans /etc/modprobe.d, puis"
            " recharger le module"
        )
    dossier = spec_parc.dossier_parc(PARC, _racine())
    if dossier.exists():
        manques.append(
            f"le parc {PARC} existe déjà ({dossier}) —"
            " ./long_test/opentofu_proxmox.py --detruire"
        )
    autres = autre_descente()
    if autres:
        manques.append(
            f"un test long tourne ({', '.join(map(str, autres))}) —"
            " attendre qu'il finisse"
        )
    return manques


class Descente(deep_proxmox.Descente):
    """L'étage 1 de `deep_proxmox`, puis les étapes OpenTofu sur lui."""

    OUTIL = OUTIL
    NOM_BASE = NOM_BASE

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.etapes = {}
        self._todo_inst = None

    def uuid_libvirt(self, nom):
        """Comme la base, sans `sudo` à blanc : rien n'a été créé."""
        if self.dry_run:
            return ""
        return deep_proxmox.Descente.uuid_libvirt(nom)

    def _todo(self):
        """Une instance de TODO sans constructeur, comme `descente` : seuls
        ses helpers ssh, Proxmox et OpenTofu servent."""
        if self._todo_inst is None:
            from script.todo.todo import TODO

            self._todo_inst = TODO.__new__(TODO)
        return self._todo_inst

    def _etat(self, interrompu, en_cours=None):
        etat = super()._etat(interrompu, en_cours)
        etat["parc"] = PARC
        etat["etapes"] = {nom: dict(e) for nom, e in self.etapes.items()}
        etat["verdict"] = self.verdict()
        return etat

    def verdict(self):
        """Vrai si chacune des huit étapes est `ok`, à blanc jamais."""
        return all(
            self.etapes.get(nom, {}).get("statut") == "ok" for nom in ETAPES
        )

    def _noter(self, nom, statut, debut=None, detail=""):
        etape = {"statut": statut}
        if debut is not None:
            etape["secondes"] = int(time.time() - debut)
        if detail:
            etape["detail"] = detail
        self.etapes[nom] = etape
        self._sauver()

    def _journal_tofu(self, ligne):
        """Journal du moteur : ses lignes arrivent déjà masquées."""
        self.dire(f"      {ligne}")

    # ---------------------------------------------------------------- #
    # La course
    # ---------------------------------------------------------------- #
    def parcourir(self):
        """L'étage 1, puis les étapes tofu ; rend le rapport final.

        Le rapport rendu est recalculé après les étapes tofu, sans le
        résumé imprimé une seconde fois.
        """
        debut = time.time()
        super().parcourir()
        etage = self.etages[0] if self.etages else {}
        if self.dry_run:
            self._noter("monter_pve", "plan")
            self.plan_tofu()
        elif etage.get("ok"):
            self._noter("monter_pve", "ok", debut)
            self.etapes_tofu()
        else:
            self._noter(
                "monter_pve",
                "echec",
                debut,
                f"étage 1 arrêté à « {etage.get('etape', 'creation')} »",
            )
            for nom in ETAPES[1:]:
                self.etapes[nom] = {"statut": "saute"}
        self._bilan()
        interrompu = self.interrompu or (
            not self.dry_run and not etage.get("ok")
        )
        return self._etat(interrompu)

    def plan_tofu(self):
        """À blanc : chaque étape tofu et ce qu'elle ferait, sans rien
        lancer."""
        pve_alias = self.nom_etage(1)
        alias = f"{pve_alias}+{VM}"
        plan = (
            (
                "preparer_hote",
                "pont interne + NAT s'il manque ; rôle"
                f" {jeton_proxmox.ROLE}, utilisateur"
                f" {jeton_proxmox.UTILISATEUR}, jeton"
                f" {jeton_proxmox.UTILISATEUR}!{PARC}, contenus"
                f" {','.join(jeton_proxmox.CONTENUS_REQUIS)}",
            ),
            (
                "plan_1",
                f"tofu plan du parc {PARC} — attendu : créer vm, cloud-init"
                f" et image de {VM}, rien d'autre ; tofu show -json gardé"
                " en 0600 dans le dossier de la course",
            ),
            ("apply", f"tofu apply du plan, puis l'alias ssh {alias}"),
            ("ssh", f"ssh -o BatchMode=yes {alias} true"),
            ("plan_2", "tofu plan — attendu : aucun changement"),
            ("destroy", "tofu destroy, puis l'alias retiré"),
            ("absence", f"qm list sur {pve_alias} sans le VMID de {VM}"),
        )
        print(f"  ── OpenTofu : parc {PARC} sur {pve_alias}")
        for nom, quoi in plan:
            print(f"  ── {nom} : {quoi}")
            self.etapes[nom] = {"statut": "plan"}

    def etapes_tofu(self):
        """Les sept étapes tofu sur le Proxmox de l'étage 1.

        Un échec de préparation ou de premier plan arrête la suite, notée
        `saute`. L'apply n'arrête la suite que si `tofu apply` lui-même a
        échoué (`ctx["applique"]` absent) : dès qu'il a tourné, la VM est
        dans l'état tofu, et ssh, second plan, destroy et absence passent
        tous, quoi qu'aient rendu les sorties ou l'après-apply.
        """
        hote = {"target": self.etages[0]["alias"], "sudo": "sudo ", "jump": ""}
        ctx = {}

        def echoue(ok):
            return not ok

        def jamais(_ok):
            return False

        sequence = (
            ("preparer_hote", lambda: self._preparer_hote(hote, ctx), echoue),
            ("plan_1", lambda: self._plan_1(ctx), echoue),
            (
                "apply",
                lambda: self._apply(ctx),
                lambda _ok: "applique" not in ctx,
            ),
            ("ssh", lambda: self._ssh(ctx), jamais),
            ("plan_2", lambda: self._plan_2(ctx), jamais),
            ("destroy", lambda: self._destroy(ctx), jamais),
            ("absence", lambda: self._absence(ctx), jamais),
        )
        arret = False
        for nom, action, arret_si in sequence:
            if arret:
                self._noter(nom, "saute")
                continue
            arret = arret_si(self._etape(nom, action))

    def _etape(self, nom, action):
        """Lance `action`, qui rend (ok, détail) ; note statut, durée et
        détail au rapport. Une exception est un échec noté : le rapport
        doit survivre à l'étape qui casse."""
        self.dire(f"  ── {nom}")
        debut = time.time()
        try:
            ok, detail = action()
        except Exception as exc:  # noqa: BLE001 - noté, jamais perdu
            ok, detail = False, f"{type(exc).__name__}: {exc}"
        self._noter(nom, "ok" if ok else "echec", debut, detail)
        secondes = self.etapes[nom]["secondes"]
        self.dire(
            f"      {'✓' if ok else '✗'} {nom} en {secondes} s"
            + (f" — {detail}" if detail else "")
        )
        return ok

    def _bilan(self):
        print("")
        for nom in ETAPES:
            etape = self.etapes.get(nom, {})
            statut = etape.get("statut", "—")
            marque = {"ok": "✓", "echec": "✗", "plan": "·"}.get(statut, "—")
            duree = f"  {etape['secondes']} s" if "secondes" in etape else ""
            self.dire(f"    {marque} {nom:<14} {statut}{duree}")
        if self.dry_run:
            self.dire("  plan OpenTofu annoncé — rien n'a été lancé")
        else:
            self.dire(
                f"  {'✅' if self.verdict() else '❌'} OpenTofu sur"
                f" {self.nom_etage(1)}"
            )

    # ---------------------------------------------------------------- #
    # Les étapes, chacune rend (ok, détail)
    # ---------------------------------------------------------------- #
    def _preparer_hote(self, hote, ctx):
        """Pont interne du Proxmox, spec du parc, rôle, utilisateur, jeton.

        Le pont vient de `preparer_parent` : un Proxmox fraîchement
        installé n'en a aucun, et la résolution refuserait l'hôte. Il est
        interne, sans DHCP : la VM reçoit une adresse fixe à la résolution.
        """
        if self.preparer_parent(hote) is None:
            return False, "pont interne du Proxmox non posé"
        racine = _racine()
        spec = spec_parc.nouvelle_spec(PARC, hote["target"])
        spec["compte"]["ssh_key"] = cle_publique()
        vm = spec["vms"][0]
        vm["nom"] = VM
        vm.update(VM_RESSOURCES)
        spec_parc.sauver(spec, racine)
        brut = resolution.executer_ssh({**spec["cible"]["hote"], "sudo": ""})
        res, neuve = jeton_proxmox.preparer_hote(spec, brut, racine=racine)
        if not res.ok:
            return False, res.message
        spec_parc.sauver(neuve, racine)
        ctx["spec"] = neuve
        return True, res.message

    def _plan_1(self, ctx):
        """Premier plan : exactement la VM, son cloud-init et son image."""
        spec = ctx["spec"]
        mot = moteur.moteur_pour(spec, racine=_racine())
        ctx["moteur"] = mot
        res, changements = mot.planifier(spec, self._journal_tofu)
        if not res.ok:
            return False, res.message
        ctx["changements"] = changements
        capture = self._capturer_plan(mot, spec, "show_plan.json")
        lignes = "; ".join(moteur.formater_plan(changements))
        vus = tuple(sorted((c.action, c.ressource) for c in changements))
        vms = {
            c.vm for c in changements if c.ressource != moteur.RESSOURCE_IMAGE
        }
        if vus != PLAN_1_ATTENDU or vms != {VM}:
            return False, f"plan inattendu : {lignes}"
        return True, lignes + (f" ; plan JSON : {capture}" if capture else "")

    def dossier_captures(self):
        """`<rapport sans .json>/` : les captures de la course, en 0700.

        Un sous-dossier et non un `.json` de premier niveau : le dossier
        des rapports est balayé par `dernier_rapport`, et une capture n'y
        est pas un rapport.
        """
        return self.chemin_json[: -len(".json")]

    def _capturer_plan(self, mot, spec, nom):
        """`tofu show -json` du plan sauvé, écrit en 0600 dans
        `dossier_captures()/nom`.

        La capture passe par le moteur (`_capturer`) : même environnement,
        même masquage de stderr, et stdout n'est jamais journalisé. Le
        fichier est créé exclusivement, jamais réécrit. Rend le chemin, ou
        "" si la capture échoue.
        """
        res, sortie = mot._capturer(
            spec,
            ["show", "-json", "-no-color", moteur_tofu._PLAN],
            self._journal_tofu,
        )
        if not res.ok:
            self.dire(f"      ⚠ tofu show -json : {res.message}")
            return ""
        dossier = self.dossier_captures()
        chemin = os.path.join(dossier, nom)
        try:
            os.makedirs(dossier, mode=0o700, exist_ok=True)
            os.chmod(dossier, 0o700)
            fd = os.open(chemin, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(sortie)
        except OSError as exc:
            self.dire(f"      ⚠ capture non écrite : {exc}")
            return ""
        self.dire(f"      plan JSON (0600) : {chemin}")
        return chemin

    def _apply(self, ctx):
        """Le plan appliqué, puis l'après-apply du menu sur les VM créées."""
        spec, mot = ctx["spec"], ctx["moteur"]
        res = mot.appliquer(spec, self._journal_tofu)
        if not res.ok:
            return False, res.message
        ctx["applique"] = True
        nouvelles = moteur.vms_nouvelles(ctx["changements"])
        # Après un apply réussi, rien ne rend l'étape fausse : une sortie
        # manquante ou un après-apply qui casse est un avertissement, que
        # l'étape ssh constatera.
        try:
            sorties = mot.sorties(spec)
            ctx["sorties"] = sorties
            self._todo()._tofu_apres_apply(spec, sorties, nouvelles)
        except Exception as exc:  # noqa: BLE001 - la VM existe, on continue
            return True, f"⚠ après-apply : {type(exc).__name__}: {exc}"
        sortie = sorties.get(VM)
        if not sortie:
            return True, f"⚠ aucune sortie tofu pour {VM}"
        return True, f"vmid {sortie['vmid']}, ip {sortie['ip'] or 'dhcp'}"

    def _ssh(self, ctx):
        """`ssh -o BatchMode=yes <alias> true` par l'alias de l'après-apply,
        répété jusqu'à DELAI_SSH."""
        todo = self._todo()
        alias = todo._tofu_alias(ctx["spec"], VM)
        if not todo._ssh_config_block(alias):
            return False, f"alias {alias} absent de ~/.ssh/config"
        fin = time.time() + DELAI_SSH
        while True:
            try:
                res = subprocess.run(
                    [
                        "ssh",
                        "-o",
                        "BatchMode=yes",
                        "-o",
                        "ConnectTimeout=10",
                        alias,
                        "true",
                    ],
                    capture_output=True,
                    text=True,
                    timeout=60,
                    stdin=subprocess.DEVNULL,
                )
                if res.returncode == 0:
                    return True, alias
                dernier = pve.strip_ssh_noise(res.stderr or "").strip()
            except (OSError, subprocess.SubprocessError) as exc:
                dernier = str(exc)
            if time.time() >= fin:
                return False, f"{alias} : {dernier[-200:] or 'muet'}"
            time.sleep(10)

    def _plan_2(self, ctx):
        """Second plan : la spec résolue au premier ne change plus rien."""
        res, changements = ctx["moteur"].planifier(
            ctx["spec"], self._journal_tofu
        )
        if not res.ok:
            return False, res.message
        if changements:
            capture = self._capturer_plan(
                ctx["moteur"], ctx["spec"], "show_plan_2.json"
            )
            lignes = "; ".join(moteur.formater_plan(changements))
            return False, lignes + (
                f" ; plan JSON : {capture}" if capture else ""
            )
        return True, "aucun changement"

    def _destroy(self, ctx):
        spec = ctx["spec"]
        res = ctx["moteur"].detruire(spec, self._journal_tofu)
        if not res.ok:
            return False, res.message
        self._todo()._tofu_apres_destroy(spec)
        return True, res.message

    def _absence(self, ctx):
        """`qm list` sur le Proxmox : le VMID de la VM n'y figure plus."""
        spec = ctx["spec"]
        sortie = (ctx.get("sorties") or {}).get(VM) or {}
        vmid = sortie.get("vmid") or spec["vms"][0].get("vmid")
        if not vmid:
            return False, "VMID inconnu"
        executer = resolution.executer_ssh(spec["cible"]["hote"])
        code, texte = executer("qm list")
        if code:
            return False, f"qm list illisible (code {code})"
        presents = {v["vmid"] for v in pve.parse_qm_list(texte)}
        if int(vmid) in presents:
            return False, f"vmid {vmid} encore listé par qm list"
        return True, f"vmid {vmid} absent de qm list"


FAMILLE = Famille(OUTIL, NOM_BASE, deep_proxmox.detruire_une)


def defaire(dry_run=False):
    """Défait le Proxmox du dernier rapport, puis retire le parc et les
    captures de ce rapport.

    Le parc ne part qu'après un Proxmox défait d'après un rapport : sa VM
    vivait sur le disque du Proxmox, que `virsh undefine
    --remove-all-storage` a effacé avec elle. Un `tofu destroy` avant la
    confirmation détruirait sans accord, et après, il ne joindrait plus
    rien. Sans rapport à défaire, ou avec un Proxmox resté debout, le parc
    est gardé : rien ne dit que sa VM a disparu.

    Le rapport est lu par le même `dernier_rapport` que `detruire`, sur les
    mêmes fichiers : c'est celui qu'il défait.
    """
    journal = os.path.expanduser(
        f"~/.erplibre/longtest/{NOM_BASE}"
        f"-{time.strftime('%Y%m%d-%H%M%S')}.log"
    )
    os.makedirs(os.path.dirname(journal), exist_ok=True)
    rapport = dernier_rapport(OUTIL, NOM_BASE)
    code = detruire(FAMILLE, journal, dry_run=dry_run)
    dossier = spec_parc.dossier_parc(PARC, _racine())
    fichier = rapport.get("fichier") or ""
    captures = fichier[: -len(".json")] if fichier.endswith(".json") else ""
    a_retirer = [d for d in (str(dossier), captures) if d and os.path.isdir(d)]
    if not a_retirer:
        return code
    if not rapport:
        dire(f"  parc {PARC} gardé : aucun rapport défait", journal)
        return code
    if dry_run:
        for d in a_retirer:
            dire(f"  [à blanc] retiré : {d}", journal)
        return code
    if code:
        dire(f"  parc {PARC} gardé : le Proxmox n'est pas défait", journal)
        return code
    if dossier.exists():
        _oublier_parc(journal)
    for d in a_retirer:
        shutil.rmtree(d)
        dire(f"  ✓ retiré : {d}", journal)
    return code


def _oublier_parc(journal):
    """Retire l'alias ssh de la VM du parc et dit ce que l'état tofu
    décrivait encore. Au mieux : un parc illisible n'arrête rien."""
    try:
        spec = spec_parc.charger(PARC, _racine())
    except spec_parc.SpecInvalide:
        return
    try:
        from script.todo.todo import TODO

        TODO.__new__(TODO)._tofu_apres_destroy(spec)
        mot = moteur.moteur_pour(spec, racine=_racine())
        restes = [x for x in mot.etat(spec) if x.startswith("proxmox_")]
    except Exception as err:  # noqa: BLE001 - jamais bloquer le défaire
        dire(f"  ⚠ parc {PARC} : {err}", journal)
        return
    if restes:
        dire(
            f"  état tofu : {len(restes)} ressource(s), effacée(s) avec le"
            " disque du Proxmox",
            journal,
        )


def principal(argv=None):
    parseur = argparse.ArgumentParser(description=DESCRIPTION)
    parseur.add_argument("--dry-run", action="store_true")
    parseur.add_argument("--detruire", action="store_true")
    args = parseur.parse_args(argv)
    if args.detruire:
        return defaire(args.dry_run)
    if not args.dry_run:
        manques = prealables()
        if manques:
            print("\n  ✗ prérequis manquants — rien n'a été créé :")
            for manque in manques:
                print(f"    ✗ {manque}")
            print("")
            return 1
    courses = []

    def fabrique(*a, **kw):
        course = Descente(*a, **kw)
        courses.append(course)
        return course

    code = mener(
        ["--depth", "1"] + (["--dry-run"] if args.dry_run else []),
        DESCRIPTION,
        FAMILLE,
        fabrique,
    )
    # `mener` juge l'étage 1 ; le verdict OpenTofu s'y ajoute.
    if args.dry_run or code:
        return code
    return 0 if courses and courses[0].verdict() else 1


if __name__ == "__main__":
    sys.exit(principal())
