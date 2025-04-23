#!/usr/bin/env python3

import argparse
import os
import subprocess


def get_config():
    """Parse command line arguments, extracting the config file name,
    returning the union of config file and command line arguments

    :return: dict of config file settings and command line arguments
    """

    parser = argparse.ArgumentParser(
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description="Génère une paire de clé SSH pour créer le royaume.",
    )
    parser.add_argument(
        "--royaume",
        required=True,
        help="Le nom du royaume ou de l'environnement cible.",
    )

    args = parser.parse_args()
    return args


def generer_cles_ssh(config):
    # Définir le chemin du répertoire .ssh
    repertoire_ssh = os.path.expanduser("~/.ssh")
    if not os.path.exists(repertoire_ssh):
        os.makedirs(repertoire_ssh)
        print(f"📁 Répertoire {repertoire_ssh} créé.")

    # Chemins des fichiers de clés
    cle_privee = os.path.join(
        repertoire_ssh, f"id_ed25519_ansible_{config.royaume}"
    )
    cle_publique = f"{cle_privee}.pub"

    # Générer la paire de clés SSH
    lst_cmd = [
        "ssh-keygen",
        "-t",
        "ed25519",
        "-f",
        cle_privee,
        "-C",
        f"Cle ansible pour le royaume {config.royaume}",
        "-N",
        "",
    ]
    try:
        subprocess.run(lst_cmd, check=True)
        print(
            f"✅ Paires de clés SSH générées :\n- Clé privée : {cle_privee}\n-"
            f" Clé publique : {cle_publique}"
        )
    except subprocess.CalledProcessError as e:
        print(f"❌ Erreur lors de la génération des clés SSH : {e}")


if __name__ == "__main__":
    config = get_config()
    generer_cles_ssh(config)
