#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""L'exécuteur : tout ce qui touche vraiment la machine passe par ici.

Un pilote VPN ne lance jamais rien lui-même. Il DEMANDE — « écris ce
fichier », « lance cette commande » — et cet objet exécute, ou se contente
d'afficher quand on l'a lancé à blanc. Trois choses en découlent :

1. `--dry-run` n'est pas une branche parallèle dans chaque pilote : c'est un
   drapeau ici. Ce qui s'affiche est exactement ce qui s'exécuterait.
2. Chaque opération est ENREGISTRÉE dans `ops`. Les tests unitaires peuvent
   donc vérifier, sans root et sans serveur en face, qu'aucun secret n'a
   atterri dans une ligne de commande.
3. La règle « les secrets ne passent que par l'entrée standard » est tenue en
   UN endroit, pas dans cinq pilotes.

Pourquoi l'entrée standard : `/proc/<pid>/cmdline` est lisible par tout
utilisateur de la machine, `/proc/<pid>/environ` par le seul propriétaire du
processus. Un mot de passe en argument est visible de tous pendant toute la
durée de la commande.
"""
from __future__ import annotations

import shlex
import subprocess
import sys

# Le même masque que le coffre : deux masques différents dans la même
# sortie feraient croire à deux natures de secret.
from script.vpn.vault import MASK

# Marqueurs des blocs gérés dans les fichiers de configuration du système.
# Reconnaissables, uniques, et ils DISENT de ne pas éditer à la main.
BLOCK_BEGIN = "# >>> erplibre-vpn %s — généré, ne pas éditer"
BLOCK_END = "# <<< erplibre-vpn %s"


def replace_block(text: str, marker: str, body: str) -> str:
    """`text` où le bloc `marker` vaut `body`. Ajouté à la fin s'il est
    absent, retiré si `body` est vide.

    Fonction PURE : c'est elle qui décide de ce qu'on écrit dans
    /etc/ipsec.conf, et un test doit pouvoir la juger sans /etc.
    """
    begin = BLOCK_BEGIN % marker
    end = BLOCK_END % marker
    lines = text.splitlines()
    out, inside, seen = [], False, False
    for line in lines:
        if line.strip() == begin:
            inside, seen = True, True
            if body:
                out.append(begin)
                out.extend(body.rstrip("\n").splitlines())
                out.append(end)
            continue
        if inside:
            if line.strip() == end:
                inside = False
            continue
        out.append(line)
    if not seen and body:
        if out and out[-1].strip():
            out.append("")
        out.append(begin)
        out.extend(body.rstrip("\n").splitlines())
        out.append(end)
    return "\n".join(out).rstrip("\n") + "\n" if out or body else ""


class Runner:
    """Exécute (ou montre) les opérations demandées par un pilote."""

    def __init__(self, dry_run=False, quiet=False, redactor=None, sudo=True):
        self.dry_run = dry_run
        self.quiet = quiet
        # `redactor` masque les secrets dans TOUT ce qui s'affiche. Sans lui
        # rien n'est masqué : c'est voulu, l'appelant doit le fournir dès
        # qu'un secret est en jeu, et un test l'oublie sans risque.
        self.redactor = redactor or (lambda text: text)
        self.use_sudo = sudo
        self.ops: list[dict] = []
        self.failures: list[str] = []

    def add_secret(self, value):
        """Masque `value` dans tout ce qui s'affichera DÉSORMAIS.

        Le masquage est monté une fois pour toutes au démarrage, à partir de
        ce que le coffre a rendu. Mais un secret peut NAÎTRE en cours de
        route : un jeton de session obtenu par une authentification web
        n'existe pas avant qu'elle aboutisse, et il ne doit pas moins être
        masqué que le mot de passe qui l'a produit.

        Sous huit caractères, on ne masque pas : une valeur courte se
        retrouve par hasard dans un chemin ou un nom d'interface, et on
        masquerait du texte utile en croyant protéger un secret.
        """
        value = str(value or "")
        if len(value) < 8:
            return
        previous = self.redactor
        self.redactor = lambda text: previous(text).replace(value, MASK)

    # ------------------------------------------------------------------
    # Affichage
    # ------------------------------------------------------------------
    def info(self, message):
        if not self.quiet:
            print(self.redactor(message))

    def step(self, label):
        self.info(f"  → {label}")

    def ok(self, message):
        self.info(f"  ✓ {message}")

    def warn(self, message):
        self.info(f"  ! {message}")

    def fail(self, message):
        self.failures.append(message)
        self.info(f"  ✗ {message}")

    # ------------------------------------------------------------------
    # Commandes
    # ------------------------------------------------------------------
    def cmd(
        self,
        label,
        command,
        stdin=None,
        secret_stdin=False,
        check=True,
        capture=False,
        sudo=None,
        timeout=None,
        allow_fail_message=None,
    ):
        """Lance `command`. Rend (code de retour, sortie).

        `stdin` est le seul chemin par lequel un secret entre dans un
        processus. `secret_stdin` ne change PAS l'exécution : il dit à
        l'affichage et aux tests que ce contenu ne doit jamais être montré.

        `capture` vaut True (sortie et erreurs lues, donc invisibles),
        False (tout à l'écran, rien de lu), ou « stdout » — la sortie est
        lue, les erreurs restent à l'écran. Ce troisième cas existe pour
        une commande qui RETOURNE un secret sur sa sortie tout en parlant
        sur ses erreurs : capturer les deux ferait attendre l'utilisateur
        en silence devant une authentification qui réclame son geste.

        Faute de `stdin`, l'entrée est /dev/null et JAMAIS le terminal
        hérité. Une commande qui reçoit un terminal sur son entrée peut
        appeler `tcsetattr` ; hors du groupe de processus d'avant-plan,
        elle reçoit alors SIGTTOU et s'ARRÊTE — état T, que ni SIGINT ni
        SIGTERM ne lèvent, et qui garde les verrous déjà pris. Le cas se
        produit quand la sortie est capturée : sudo alloue un
        pseudo-terminal pour l'entrée pendant que la sortie part dans un
        tuyau, et le groupe d'avant-plan de ce terminal n'est pas celui de
        la commande. Rien ici n'a besoin de lire l'humain : les questions
        passent par `confirm`, dans CE processus, et un secret arrive par
        `stdin`. Une invite de mot de passe sudo n'en souffre pas — sudo
        ouvre /dev/tty, pas son entrée standard.
        """
        full = command
        if sudo is None:
            sudo = self.use_sudo
        if sudo:
            full = f"sudo {command}"
        self.ops.append(
            {
                "kind": "cmd",
                "label": label,
                "cmd": full,
                "stdin": stdin,
                "secret_stdin": secret_stdin,
            }
        )
        shown = full if not stdin else f"{full}   « sur l'entrée standard »"
        self.step(f"{label}\n      {self.redactor(shown)}")
        if self.dry_run:
            return 0, ""
        try:
            proc = subprocess.run(
                full,
                shell=True,
                input=stdin,
                # Rien à fournir : /dev/null, et jamais le terminal hérité
                # (voir la docstring). Quand `input` porte un contenu,
                # subprocess branche lui-même le tuyau et `stdin` doit
                # rester None — les deux ensemble sont refusés.
                stdin=subprocess.DEVNULL if stdin is None else None,
                text=True,
                timeout=timeout,
                stdout=subprocess.PIPE if capture else None,
                stderr=(subprocess.STDOUT if capture is True else None),
            )
            code, out = proc.returncode, proc.stdout or ""
        except subprocess.TimeoutExpired:
            # Le délai rend la main à l'appelant ; il ne garantit pas que
            # la commande soit morte. `shell=True` met un shell entre nous
            # et le vrai travail, et subprocess ne tue que ce shell — un
            # `sudo apt-get` lancé par lui devient orphelin et continue,
            # verrous compris. D'où le code 124 et un échec ANNONCÉ plutôt
            # qu'un silence : la suite se juge sur un état inconnu.
            code, out = 124, ""
            self.fail(f"{label} : délai dépassé ({timeout} s)")
            return code, out
        if code != 0 and check:
            self.fail(allow_fail_message or f"{label} (code {code})")
        return code, out

    def read_root_file(self, path):
        """Contenu d'un fichier que seul root peut lire, "" s'il n'existe
        pas. Passe par `sudo cat` : /etc/ipsec.secrets est en 0600."""
        code, out = self.cmd(
            f"lire {path}",
            f"cat {shlex.quote(path)}",
            check=False,
            capture=True,
        )
        return out if code == 0 else ""

    def propose(self, constat, command, sudo=True, question=None):
        """Propose un correctif, l'applique si on l'accepte.

        Rend True seulement s'il a été appliqué ET a réussi.

        L'outil sait souvent quoi faire : renvoyer l'utilisateur taper la
        commande lui-même, puis tout relancer, c'est lui faire porter un
        travail qu'on a déjà identifié. On demande donc — on ne le fait pas
        d'office : arrêter un service du système est une décision, pas un
        détail d'implémentation.

        Refusé d'office à blanc, et quand l'entrée standard n'est pas un
        terminal (cron, script, journal rejoué) : un outil qui modifie un
        service parce que PERSONNE n'a répondu serait pire que le problème
        qu'il résout.
        """
        montrable = f"{'sudo ' if sudo else ''}{command}"
        if self.dry_run:
            self.info(f"      (à blanc : proposerait « {montrable} »)")
            return False
        self.info(f"      → Correctif proposé : {montrable}")
        if not sys.stdin.isatty():
            self.warn(
                "Pas de terminal pour demander : correctif NON appliqué."
            )
            return False
        if not self.confirm(question or "Appliquer maintenant ?"):
            self.info("      Laissé en place.")
            return False
        code, _ = self.cmd(
            f"appliquer le correctif : {constat}",
            command,
            sudo=sudo,
            check=False,
        )
        return code == 0

    def confirm(self, question) -> bool:
        """Pose `question` et rend vrai si la réponse est oui.

        La question est une ligne COMPLÈTE, terminée par une fin de ligne,
        et non un prompt passé à `input`. Un lanceur qui relaie notre
        sortie en la lisant ligne par ligne garde une ligne partielle dans
        son tampon jusqu'à la fin de ligne suivante : la question reste
        alors invisible jusqu'à ce que la réponse ait déjà été donnée, puis
        ressort collée au texte qui la suit. C'est le cas du menu TODO, qui
        lit par `readline` PARCE QUE le masquage des secrets travaille sur
        une ligne entière — un secret à cheval sur deux morceaux passerait
        au travers. La contrainte vient donc d'une garantie, elle ne se
        contourne pas.

        Affichée même quand l'exécuteur est silencieux : on s'apprête à
        BLOQUER dessus, et une question invisible est une attente sans
        raison apparente.
        """
        print(self.redactor(f"      {question} [o/N]"))
        return input().strip().lower() in ("o", "oui", "y", "yes")

    # ------------------------------------------------------------------
    # Fichiers
    # ------------------------------------------------------------------
    def write(self, path, content, mode="0600", secret=False, label=None):
        """Écrit `content` dans `path`, en root, de façon ATOMIQUE.

        Le contenu passe par l'entrée standard, jamais par la ligne de
        commande. `umask` donne le bon mode dès la création, `chmod` le
        rend déterministe même si le fichier existait, et `mv` publie le
        résultat d'un coup — un fichier de configuration à moitié écrit
        vaut souvent moins qu'un fichier absent.
        """
        quoted = shlex.quote(path)
        tmp = shlex.quote(f"{path}.erplibre-tmp")
        umask = "077" if secret else "022"
        script = (
            f"umask {umask}; cat > {tmp}"
            f" && chmod {mode} {tmp}"
            f" && mv -f {tmp} {quoted}"
        )
        self.ops.append(
            {
                "kind": "write",
                "path": path,
                "content": content,
                "mode": mode,
                "secret": secret,
            }
        )
        self.step(label or f"écrire {path} ({mode})")
        if self.dry_run:
            body = "********" if secret else content
            for line in body.rstrip("\n").splitlines():
                self.info(f"      │ {line}")
            return 0
        code, _ = self.cmd(
            f"écrire {path}",
            f"sh -c {shlex.quote(script)}",
            stdin=content,
            secret_stdin=secret,
            check=True,
        )
        return code

    def mkdir(self, path, mode="0700"):
        return self.cmd(
            f"créer {path} ({mode})",
            f"install -d -m {mode} {shlex.quote(path)}",
        )[0]

    def remove(self, path):
        return self.cmd(
            f"effacer {path}", f"rm -rf -- {shlex.quote(path)}", check=False
        )[0]

    def backup_once(self, path):
        """Copie `path` en `.erplibre.bak` s'il n'y en a pas encore.

        Une seule fois : la sauvegarde doit garder l'état ORIGINAL, pas
        celui d'avant-hier. On touche à l'ipsec.conf de quelqu'un.
        """
        backup = f"{path}.erplibre.bak"
        source, target = shlex.quote(path), shlex.quote(backup)
        script = (
            f"[ -f {source} ] && [ ! -f {target} ]"
            f" && cp -p {source} {target} || true"
        )
        return self.cmd(
            f"sauvegarder {path} → {backup}",
            f"sh -c {shlex.quote(script)}",
            check=False,
        )[0]

    def block(self, path, marker, body, mode="0644", secret=False):
        """Pose (ou retire, si `body` est vide) un bloc marqué dans `path`.

        Rend True s'il a fallu écrire, False si le bloc était déjà en place.
        L'appelant s'en sert pour ne recharger un démon que quand sa
        configuration a réellement bougé.

        Le fichier est relu avant d'être réécrit : on ajoute une section à
        la configuration de l'utilisateur, on ne la remplace pas.
        """
        current = self.read_root_file(path)
        if self.dry_run and not current:
            current = f"# ({path} sera relu à l'exécution)\n"
        new = replace_block(current, marker, body)
        if new == current:
            self.ok(f"{path} : bloc « {marker} » déjà à jour")
            return False
        self.backup_once(path)
        self.write(
            path,
            new,
            mode=mode,
            secret=secret,
            label=f"{'retirer' if not body else 'poser'} le bloc"
            f" « {marker} » dans {path}",
        )
        return True

    # ------------------------------------------------------------------
    # Logique Python (résolution, attente, routes)
    # ------------------------------------------------------------------
    def call(self, label, function, dry_safe=False):
        """Exécute une étape écrite en Python.

        `dry_safe` marque celles qui ne font que LIRE l'état de la machine
        (résoudre un nom, lire une table de routage) : elles tournent même
        à blanc, parce que sans elles le plan affiché serait creux.
        """
        self.ops.append({"kind": "call", "label": label})
        self.step(label)
        if self.dry_run and not dry_safe:
            return None
        return function()
