#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""La clé SSH : une paire générée par ssh-keygen, après quelques questions.

La clé privée ne quitte jamais ce poste ; la clé publique (`.pub`) se copie
sur les serveurs. ssh-keygen demande lui-même la phrase de passe, dans le
terminal : elle ne passe jamais en argument, où `ps` la montrerait.

Le fichier ne doit pas pouvoir être commité : `chemin_commitable` du sceau
refuse un chemin qu'un dépôt git suivrait. Un fichier existant n'est jamais
remplacé : perdre une clé coupe l'accès aux serveurs qui l'approuvent.
"""

import getpass
import os
import socket
import subprocess

from script.todo.seal_menu import chemin_commitable, format_commande
from script.todo.todo_i18n import t

DOSSIER_SSH = os.path.join("~", ".ssh")
# Les types proposés, dans l'ordre du choix : ed25519, court et sûr, que tout
# OpenSSH récent accepte ; RSA 4096 pour un serveur trop ancien pour ed25519.
TYPES_CLE = ("ed25519", "rsa")
BITS_RSA = 4096
# Tours de la dérivation de la phrase de passe (bcrypt) : un mot de passe
# volé avec la clé coûte d'autant plus cher à deviner.
TOURS_KDF = 100


def commande_ssh_keygen(chemin, type_cle, commentaire):
    """La commande ssh-keygen, en liste d'arguments, qui crée la paire
    ``chemin`` et ``chemin.pub`` : sans phrase de passe en argument, que
    ssh-keygen demande lui-même."""
    commande = ["ssh-keygen", "-t", type_cle]
    if type_cle == "rsa":
        commande += ["-b", str(BITS_RSA)]
    commande += ["-a", str(TOURS_KDF), "-f", chemin, "-C", commentaire]
    return commande


def commentaire_par_defaut():
    """``utilisateur@hôte`` : ce qui dit, sur un serveur, d'où vient la
    clé."""
    return f"{getpass.getuser()}@{socket.gethostname()}"


class SshKeyMenuMixin:
    def execute_generate_ssh_key(self):
        print(t("SSH key"))
        print(
            t(
                "An SSH key is a pair: the private key never leaves this"
                " computer, the public key (.pub) is copied to the servers"
                " that should accept it."
            )
        )
        type_cle = self._ssh_key_ask_type()
        if type_cle is None:
            return
        chemin = self._ssh_key_ask_path(type_cle)
        if chemin is None:
            return
        defaut = commentaire_par_defaut()
        commentaire = (
            input(
                f"💬 {t('Comment of the key (default: %s): ') % defaut}"
            ).strip()
            or defaut
        )
        commande = commande_ssh_keygen(chemin, type_cle, commentaire)
        print(f"\n{t('Command run:')}")
        print(f"$ {format_commande(commande)}")
        self._ssh_key_explain(type_cle)
        print(
            t(
                "ssh-keygen asks for the passphrase next: it protects the key"
                " if the file is copied. Leave it empty only for a key used by"
                " an automated task."
            )
        )
        try:
            resultat = subprocess.run(commande)
        except OSError as erreur:
            print(f"❌ {t('ssh-keygen failed:')} {erreur}")
            return
        if resultat.returncode != 0 or not os.path.isfile(f"{chemin}.pub"):
            print(f"❌ {t('ssh-keygen failed:')} {resultat.returncode}")
            return
        self._ssh_key_report(chemin)

    def _ssh_key_ask_type(self):
        """Le type de clé choisi, ou None sur une réponse illisible."""
        reponse = input(
            f"💬 {t('Key type: 1. ed25519 (recommended), 2. RSA 4096 (old servers) (default: 1): ')}"
        ).strip()
        choix = {"": 0, "1": 0, "2": 1}.get(reponse)
        if choix is None:
            print(f"{t('Error, cannot understand value')} '{reponse}'")
            return None
        return TYPES_CLE[choix]

    def _ssh_key_ask_path(self, type_cle):
        """Le chemin absolu de la clé privée, son dossier créé en 0700, ou
        None. Un dossier donné reçoit le nom par défaut. Sont refusés : un
        fichier ou un lien qui existe déjà, même orphelin (ssh-keygen écrit
        à travers un lien, à sa cible), un chemin que git pourrait commiter,
        et un dossier qu'on ne peut pas créer."""
        nom = f"id_{type_cle}"
        defaut = os.path.join(DOSSIER_SSH, nom)
        reponse = input(
            f"💬 {t('File of the private key (default: %s): ') % defaut}"
        ).strip()
        chemin = os.path.abspath(os.path.expanduser(reponse or defaut))
        if os.path.isdir(chemin):
            chemin = os.path.join(chemin, nom)
        existants = [
            p for p in (chemin, f"{chemin}.pub") if os.path.lexists(p)
        ]
        if existants:
            print(
                f"❌ {t('A key already exists here; replacing it would cut the access of the servers that accept it:')}"
            )
            for p in existants:
                print(f"\t{p}")
            print(t("Give another file name, such as %s.") % f"{chemin}_2")
            return None
        if chemin_commitable(chemin):
            print(
                f"❌ {t('Git could commit this file, which holds a private key:')}"
            )
            print(f"\t{chemin}")
            return None
        try:
            os.makedirs(os.path.dirname(chemin), mode=0o700, exist_ok=True)
        except OSError as erreur:
            print(f"❌ {t('Cannot create the folder of the key:')} {erreur}")
            return None
        return chemin

    def _ssh_key_explain(self, type_cle):
        """La légende des options de la commande que la génération vient
        d'afficher."""
        print(f"\n{t('What the options do:')}")
        options = [("-t", t("the type of the key: %s") % type_cle)]
        if type_cle == "rsa":
            options.append(("-b", t("the size of an RSA key, in bits")))
        options += [
            (
                f"-a {TOURS_KDF}",
                t(
                    "the rounds that make a stolen passphrase-protected key"
                    " slow to guess"
                ),
            ),
            ("-f", t("the file of the private key; the public key adds .pub")),
            ("-C", t("the comment that names the key on the servers")),
        ]
        for option, sens in options:
            print(f"\t{option:<10} {sens}")

    def _ssh_key_report(self, chemin):
        """Affiche la clé publique, son empreinte et la suite."""
        publique = f"{chemin}.pub"
        print(f"✅ {t('Key written:')}")
        print(f"\t{chemin}")
        print(f"\t{publique}")
        with open(publique, encoding="utf-8") as fichier:
            print(f"\n{t('Public key, to copy to the servers:')}")
            print(fichier.read().strip())
        empreinte = subprocess.run(
            ["ssh-keygen", "-l", "-f", publique],
            capture_output=True,
            text=True,
        )
        if empreinte.returncode == 0:
            print(f"{t('Fingerprint:')} {empreinte.stdout.strip()}")
        print(t("Next, to a server: ssh-copy-id -i %s user@server") % publique)
