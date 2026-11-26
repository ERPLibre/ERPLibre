# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Moteur OpenTofu : spec résolue, `main.tf.json`, sous-commandes `tofu`.

`MoteurTofu` travaille dans `private/opentofu/<parc>/.tofu/`. Les secrets du
parc passent par l'environnement du sous-processus (`coffre.environnement`),
jamais par la ligne de commande ni par le document ; chaque ligne de sortie
est masquée par `coffre.masquer` avant d'atteindre le journal. `appliquer`
n'applique que le plan sauvé par `planifier`, jamais un nouveau calcul.
`traduire_plan` convertit la sortie de `tofu show -json` en `Changement`
indépendants du moteur.
"""

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

from script.opentofu import coffre, rendu_proxmox, resolution
from script.opentofu import spec as spec_parc
from script.opentofu.moteur import Changement, Moteur, Resultat, enregistrer
from script.todo.todo_i18n import t

_DOCUMENT = "main.tf.json"
_PLAN = "plan.bin"
_PROVIDERS_INIT = ".init_providers.json"
_VERROU = "Error acquiring the state lock"
_RE_ID_VERROU = re.compile(r"\bID:\s*(\S+)")
_LONGUEUR_MAX = 60

# Type de ressource bpg → (genre affiché, préfixe posé par `rendu_proxmox`).
_RESSOURCES = {
    "proxmox_virtual_environment_vm": ("vm", "vm_"),
    "proxmox_virtual_environment_file": ("cloud-init", "ud_"),
    "proxmox_download_file": ("image", "img_"),
}
_ACTIONS = {
    ("create",): "creer",
    ("update",): "modifier",
    ("delete", "create"): "remplacer",
    ("create", "delete"): "remplacer",
    ("delete",): "detruire",
}
# Chemin d'attribut bpg, indices `0` retirés → nom du champ de la spec.
_CHAMPS_SPEC = {
    "name": "nom",
    "vm_id": "vmid",
    "node_name": "noeud",
    "started": "demarrer",
    "cpu.cores": "vcpus",
    "memory.dedicated": "ram",
    "disk.size": "disque",
    "network_device.bridge": "pont",
    "initialization.ip_config.ipv4.address": "ip",
    "initialization.ip_config.ipv4.gateway": "passerelle",
    "initialization.dns.servers": "dns",
}


def _aplatir(valeur, chemin=(), sortie=None):
    """`{chemin: feuille}` d'un arbre JSON.

    Une liste d'objets se parcourt par indice ; une liste de scalaires, un
    objet vide ou une liste vide restent des feuilles entières, sauf à la
    racine où un objet vide ne rend aucune feuille.
    """
    if sortie is None:
        sortie = {}
    if isinstance(valeur, dict) and (valeur or not chemin):
        for cle, sous in valeur.items():
            _aplatir(sous, chemin + (str(cle),), sortie)
    elif (
        isinstance(valeur, list)
        and valeur
        and all(isinstance(x, dict) for x in valeur)
    ):
        for i, sous in enumerate(valeur):
            _aplatir(sous, chemin + (str(i),), sortie)
    else:
        sortie[chemin] = valeur
    return sortie


def _marques(arbre, chemin=()):
    """Chemins marqués `true` dans un arbre `after_unknown`/`*_sensitive`."""
    if arbre is True:
        return {chemin}
    marques = set()
    if isinstance(arbre, dict):
        for cle, sous in arbre.items():
            marques |= _marques(sous, chemin + (str(cle),))
    elif isinstance(arbre, list):
        for i, sous in enumerate(arbre):
            marques |= _marques(sous, chemin + (str(i),))
    return marques


def _touche(chemin, marques):
    """Vrai si `chemin`, un de ses parents ou un de ses enfants est marqué."""
    n = len(chemin)
    return any(m[:n] == chemin or chemin[: len(m)] == m for m in marques)


def _court(valeur):
    """Valeur affichable sur une ligne, tronquée à `_LONGUEUR_MAX`."""
    if not isinstance(valeur, str):
        valeur = json.dumps(valeur, ensure_ascii=False, sort_keys=True)
    valeur = valeur.replace("\n", "\\n")
    if len(valeur) > _LONGUEUR_MAX:
        valeur = valeur[: _LONGUEUR_MAX - 3] + "..."
    return valeur


def _champ(chemin):
    """Nom affiché d'un chemin : champ de la spec quand il y correspond."""
    nom = ".".join(seg for seg in chemin if seg != "0")
    return _CHAMPS_SPEC.get(nom, nom)


def _details(change):
    """`[(champ, avant, après)]` des feuilles qui diffèrent entre les côtés.

    Un `before`/`after` absent ou `null` vaut un objet vide. Une valeur
    connue seulement après l'apply s'affiche « (après apply) » et compte
    toujours comme une différence ; une valeur sensible s'affiche
    « (sensible) », jamais en clair.
    """
    avant = _aplatir(change.get("before") or {})
    apres = _aplatir(change.get("after") or {})
    inconnues = _marques(change.get("after_unknown"))
    sens_avant = _marques(change.get("before_sensitive"))
    sens_apres = _marques(change.get("after_sensitive"))
    chemins = set(avant) | set(apres)
    # Une valeur inconnue est absente de `after` : son chemin vient de la
    # marque, sauf si un chemin plus précis la représente déjà.
    chemins |= {
        m for m in inconnues if not any(_touche(m, {c}) for c in chemins)
    }
    details = []
    for chemin in sorted(chemins):
        inconnue = _touche(chemin, inconnues)
        if not inconnue and avant.get(chemin) == apres.get(chemin):
            continue
        a = (
            t("(sensitive)")
            if _touche(chemin, sens_avant)
            else _court(avant.get(chemin))
        )
        if inconnue:
            b = t("(known after apply)")
        elif _touche(chemin, sens_apres):
            b = t("(sensitive)")
        else:
            b = _court(apres.get(chemin))
        details.append((_champ(chemin), a, b))
    return details


def _nommer(type_ressource, nom):
    """(vm, genre) d'une ressource : nom sans préfixe, `_` → `-` hors image."""
    genre, prefixe = _RESSOURCES.get(type_ressource, (type_ressource, ""))
    if prefixe and nom.startswith(prefixe):
        nom = nom[len(prefixe) :]
    if genre in ("vm", "cloud-init"):
        nom = nom.replace("_", "-")
    return nom, genre


def traduire_plan(show):
    """`Changement`s d'une sortie `tofu show -json`, sans E/S.

    `no-op`, `read`, `forget` et toute action inconnue sont ignorés. Seuls
    `modifier` et `remplacer` portent des détails : une ressource créée ou
    détruite apparaît ou disparaît entière, et lister chacun de ses
    attributs noierait le plan.
    """
    changements = []
    for rc in show.get("resource_changes") or []:
        change = rc.get("change") or {}
        action = _ACTIONS.get(tuple(change.get("actions") or ()))
        if action is None:
            continue
        vm, genre = _nommer(rc.get("type", ""), rc.get("name", ""))
        details = []
        if action in ("modifier", "remplacer"):
            details = _details(change)
        changements.append(Changement(action, vm, genre, details))
    return changements


def _message_verrou(lignes, dossier):
    """Remède d'un état verrouillé : la commande à lancer, pas lancée."""
    debut = next(i for i, ligne in enumerate(lignes) if _VERROU in ligne)
    ident = "<ID>"
    for ligne in lignes[debut:]:
        trouve = _RE_ID_VERROU.search(ligne)
        if trouve:
            ident = trouve.group(1)
            break
    return t(
        "The tofu state is locked. If no other tofu is running, release it "
        "from {dossier} with: tofu force-unlock {id}"
    ).format(dossier=dossier, id=ident)


class MoteurTofu(Moteur):
    """Moteur `tofu` d'un parc.

    `binaire`, `executer` et `mod_qemu` remplacent l'outil trouvé sur la
    machine, l'exécuteur SSH de l'hôte de la spec et `deploy_qemu` ;
    `racine` est le dossier des parcs.
    """

    nom = "tofu"

    def __init__(
        self,
        binaire=None,
        executer=None,
        mod_qemu=None,
        racine=spec_parc.RACINE_PARCS,
    ):
        self._binaire = binaire
        self._executer = executer
        self._mod_qemu = mod_qemu
        self.racine = Path(racine)

    # Outil et dossiers

    def binaire(self):
        """Chemin de `tofu` : celui donné, le PATH, puis ~/.local/bin."""
        if self._binaire:
            return self._binaire
        trouve = shutil.which("tofu")
        if trouve:
            return trouve
        local = Path.home() / ".local" / "bin" / "tofu"
        if local.is_file() and os.access(local, os.X_OK):
            return str(local)
        return None

    def dossier_travail(self, spec):
        """`<racine>/<parc>/.tofu` ; ValueError sur un nom de parc invalide."""
        return spec_parc.dossier_parc(spec["nom"], self.racine) / ".tofu"

    def _creer_dossier(self, spec):
        parc = spec_parc.dossier_parc(spec["nom"], self.racine)
        parc.mkdir(mode=0o700, parents=True, exist_ok=True)
        dossier = parc / ".tofu"
        dossier.mkdir(mode=0o700, exist_ok=True)
        return dossier

    @staticmethod
    def _effacer_plan(dossier):
        (dossier / _PLAN).unlink(missing_ok=True)

    @staticmethod
    def _initialise(dossier):
        return (dossier / ".terraform").is_dir()

    # Sous-processus

    def _contexte(self, spec):
        """(binaire, dossier, env, secrets) d'un lancement, ou un `Resultat`.

        L'environnement est construit avant la lecture des secrets : il crée
        la phrase d'état au premier appel, et elle doit être masquée aussi.
        """
        binaire = self.binaire()
        if not binaire:
            return Resultat(False, _remede_absent(), 127)
        try:
            dossier = self._creer_dossier(spec)
            env = coffre.environnement(spec["nom"], racine=self.racine)
            secrets_parc = coffre.lire(spec["nom"], self.racine)
        except (OSError, ValueError) as exc:
            return Resultat(False, str(exc), 1)
        return binaire, dossier, env, secrets_parc

    def _conclure(self, args, code, lignes, interrompu, dossier):
        if interrompu:
            return Resultat(
                False,
                t(
                    "Interrupted: tofu stopped; plan again to see where the "
                    "fleet stands."
                ),
                code,
            )
        if any(_VERROU in ligne for ligne in lignes):
            return Resultat(False, _message_verrou(lignes, dossier), code)
        if code != 0:
            return Resultat(
                False,
                t("tofu {commande} failed (exit {code}).").format(
                    commande=args[0], code=code
                ),
                code,
            )
        return Resultat(True)

    def _diffuser(self, spec, args, journal):
        """Lance `tofu args`, sortie et erreurs fusionnées, ligne à ligne.

        Rend `(Resultat, lignes masquées)`. Sur Ctrl-C, aucun signal n'est
        envoyé en plus : `tofu`, du même groupe de processus, a reçu le sien
        et s'arrête proprement en libérant son verrou ; la lecture continue
        jusqu'à sa fin.
        """
        contexte = self._contexte(spec)
        if isinstance(contexte, Resultat):
            return contexte, []
        binaire, dossier, env, secrets_parc = contexte
        lignes = []

        def recevoir(brute):
            ligne = coffre.masquer(brute.rstrip("\n"), secrets_parc)
            lignes.append(ligne)
            journal(ligne)

        journal("$ tofu " + " ".join(args))
        try:
            proc = subprocess.Popen(
                [binaire, *args],
                cwd=dossier,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
        except OSError as exc:
            return Resultat(False, _message_lancement(exc), 127), []
        interrompu = False
        with proc:
            while True:
                try:
                    for brute in proc.stdout:
                        recevoir(brute)
                    code = proc.wait()
                    break
                except KeyboardInterrupt:
                    interrompu = True
        return self._conclure(args, code, lignes, interrompu, dossier), lignes

    def _capturer(self, spec, args, journal):
        """Lance `tofu args` dont la sortie standard est un document JSON.

        Rend `(Resultat, stdout)` : stdout n'est pas journalisé (un plan y
        porte les valeurs sensibles en clair), stderr l'est, masqué.
        """
        contexte = self._contexte(spec)
        if isinstance(contexte, Resultat):
            return contexte, ""
        binaire, dossier, env, secrets_parc = contexte
        try:
            proc = subprocess.Popen(
                [binaire, *args],
                cwd=dossier,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
        except OSError as exc:
            return Resultat(False, _message_lancement(exc), 127), ""
        interrompu = False
        while True:
            try:
                sortie, erreurs = proc.communicate()
                break
            except KeyboardInterrupt:
                interrompu = True
        lignes = [coffre.masquer(x, secrets_parc) for x in erreurs.splitlines()]
        for ligne in lignes:
            journal(ligne)
        res = self._conclure(args, proc.returncode, lignes, interrompu, dossier)
        return res, sortie

    # Étapes

    def _mod(self):
        if self._mod_qemu is None:
            self._mod_qemu = resolution.charger_deploy_qemu()
        return self._mod_qemu

    def _resoudre_et_rendre(self, spec):
        """Résout `spec` (sauvée et mise à jour en place si elle change),
        écrit `main.tf.json` et efface le plan précédent ; rend le document.
        """
        mod = self._mod()
        erreurs = spec_parc.valider(spec, mod.DISTROS)
        if erreurs:
            raise ValueError("\n".join(erreurs))
        cible = spec["cible"]
        executer = self._executer or resolution.executer_ssh(cible["hote"])
        adresse = ""
        if not cible.get("api_url"):
            adresse = resolution.adresse_hote(cible["hote"]["target"])
        neuve, change = resolution.resoudre(spec, executer, adresse)
        if change:
            spec_parc.sauver(neuve, self.racine)
            spec.clear()
            spec.update(neuve)
        donnees = {
            vm["nom"]: resolution.donnees_vm(spec, vm, mod)
            for vm in spec["vms"]
        }
        document = rendu_proxmox.rendre(spec, donnees, coffre.charger_conf())
        dossier = self._creer_dossier(spec)
        self._effacer_plan(dossier)
        (dossier / _DOCUMENT).write_text(
            json.dumps(document, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return document

    def _init_requis(self, dossier, providers):
        """Vrai sans `.terraform/` ou si les fournisseurs ont changé."""
        if not self._initialise(dossier):
            return True
        try:
            connus = json.loads((dossier / _PROVIDERS_INIT).read_text("utf-8"))
        except (OSError, ValueError):
            return True
        return connus != providers

    def _preparer(self, spec, journal):
        """Résolution, rendu, puis `tofu init` quand il est requis."""
        if not self.binaire():
            return Resultat(False, _remede_absent(), 127)
        try:
            document = self._resoudre_et_rendre(spec)
        except (resolution.ResolutionImpossible, ValueError, OSError) as exc:
            return Resultat(False, str(exc), 1)
        dossier = self.dossier_travail(spec)
        providers = document["terraform"]["required_providers"]
        if self._init_requis(dossier, providers):
            res, _ = self._diffuser(
                spec, ["init", "-input=false", "-no-color"], journal
            )
            if not res.ok:
                return res
            (dossier / _PROVIDERS_INIT).write_text(
                json.dumps(providers, sort_keys=True) + "\n", encoding="utf-8"
            )
        return Resultat(True)

    # Interface Moteur

    def disponible(self):
        """`(True, version)` lue par `tofu version -json`, sinon le remède."""
        binaire = self.binaire()
        if not binaire:
            return False, _remede_absent()
        try:
            res = subprocess.run(
                [binaire, "version", "-json"],
                capture_output=True,
                text=True,
                timeout=30,
            )
            version = json.loads(res.stdout)["terraform_version"]
        except (
            OSError,
            subprocess.SubprocessError,
            ValueError,
            KeyError,
            TypeError,
        ) as exc:
            return False, t("tofu version -json failed: {err}").format(err=exc)
        return True, version

    def preparer(self, spec):
        """Résout, rend et initialise le dossier de travail.

        Sans journal à qui parler, les dernières lignes de `tofu` rejoignent
        le message d'un échec.
        """
        lignes = []
        res = self._preparer(spec, lignes.append)
        if not res.ok and lignes:
            res.message = "\n".join([res.message] + lignes[-10:])
        return res

    def planifier(self, spec, journal):
        """`(Resultat, [Changement])` du plan sauvé dans `.tofu/plan.bin`.

        Effet de bord : quand la résolution remplit des champs vides, la
        spec résolue est sauvée ET le dict `spec` reçu est mis à jour en
        place, pour que l'appelant affiche et réutilise les valeurs
        résolues. Toute erreur rend `(Resultat(False, message), [])`.
        """
        res = self._preparer(spec, journal)
        if not res.ok:
            return res, []
        dossier = self.dossier_travail(spec)
        res, _ = self._diffuser(
            spec,
            ["plan", "-input=false", "-no-color", "-out=" + _PLAN],
            journal,
        )
        if not res.ok:
            self._effacer_plan(dossier)
            return res, []
        res, sortie = self._capturer(
            spec, ["show", "-json", "-no-color", _PLAN], journal
        )
        # Un plan que l'écran n'a pas pu montrer ne doit pas être appliqué.
        if not res.ok:
            self._effacer_plan(dossier)
            return res, []
        try:
            changements = traduire_plan(json.loads(sortie))
        except (ValueError, AttributeError) as exc:
            self._effacer_plan(dossier)
            return (
                Resultat(
                    False, t("Unreadable tofu output: {err}").format(err=exc), 1
                ),
                [],
            )
        message = t("Plan ready: {n} change(s).").format(n=len(changements))
        return Resultat(True, message), changements

    def appliquer(self, spec, journal):
        """Applique le plan sauvé, s'il est plus récent que `main.tf.json`.

        Le plan est effacé après un apply réussi : un plan sauvé ne
        s'applique pas deux fois.
        """
        try:
            dossier = self.dossier_travail(spec)
        except ValueError as exc:
            return Resultat(False, str(exc), 1)
        plan, document = dossier / _PLAN, dossier / _DOCUMENT
        if (
            not plan.is_file()
            or not document.is_file()
            or plan.stat().st_mtime_ns < document.stat().st_mtime_ns
        ):
            return Resultat(False, t("Plan first."), 1)
        res, _ = self._diffuser(
            spec, ["apply", "-input=false", "-no-color", _PLAN], journal
        )
        if not res.ok:
            return res
        self._effacer_plan(dossier)
        return Resultat(True, t("Apply done."))

    def detruire(self, spec, journal):
        """`tofu destroy` sans question : la confirmation appartient à
        l'écran qui appelle."""
        try:
            dossier = self.dossier_travail(spec)
        except ValueError as exc:
            return Resultat(False, str(exc), 1)
        if not self._initialise(dossier) or not (dossier / _DOCUMENT).is_file():
            return Resultat(
                False, t("Nothing to destroy: this fleet has no tofu state."), 1
            )
        res, _ = self._diffuser(
            spec,
            ["destroy", "-auto-approve", "-input=false", "-no-color"],
            journal,
        )
        self._effacer_plan(dossier)
        if not res.ok:
            return res
        return Resultat(True, t("Destroy done."))

    def etat(self, spec):
        """Adresses des ressources de l'état ; l'erreur en dernière ligne."""
        if not self._initialise(self.dossier_travail(spec)):
            return []
        res, lignes = self._diffuser(spec, ["state", "list"], lambda _l: None)
        lignes = [x for x in lignes if x.strip()]
        if not res.ok:
            lignes.append(res.message)
        return lignes

    def sorties(self, spec):
        """`{vm: {"vmid": int, "ip": str}}` des sorties de l'état.

        `wait_for_ip.disabled` laisse l'IPv4 de `tofu` toujours vide : `ip`
        est l'adresse fixe de la spec sans son préfixe, "" en DHCP. Rend {}
        sans état ou sur une sortie illisible.
        """
        if not self._initialise(self.dossier_travail(spec)):
            return {}
        res, sortie = self._capturer(
            spec, ["output", "-json", "-no-color"], lambda _l: None
        )
        if not res.ok:
            return {}
        try:
            valeurs = json.loads(sortie).get("vms", {}).get("value") or {}
            ips = {vm["nom"]: vm.get("ip", "") for vm in spec["vms"]}
            return {
                nom: {
                    "vmid": int(v["vmid"]),
                    "ip": _ip_fixe(ips.get(nom, "")),
                }
                for nom, v in valeurs.items()
            }
        except (ValueError, AttributeError, KeyError, TypeError):
            return {}


def _ip_fixe(ip):
    """Adresse sans `/nn`, ou "" quand elle n'est pas fixe."""
    if not ip or ip in ("auto", "dhcp"):
        return ""
    return ip.split("/", 1)[0]


def _remede_absent():
    return t(
        "OpenTofu (tofu) is not installed: install it from the OpenTofu menu."
    )


def _message_lancement(exc):
    return t("Cannot run tofu: {err}").format(err=exc)


enregistrer("tofu", MoteurTofu)
